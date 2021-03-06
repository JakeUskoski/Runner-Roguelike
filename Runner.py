import libtcodpy as libtcod
import math
import textwrap
import shelve

#actual size of the window
SCREEN_WIDTH = 80
SCREEN_HEIGHT = 50

#size of the map
MAP_WIDTH = 80
MAP_HEIGHT = 43

#sizes and coordinates relevant for the GUI
BAR_WIDTH = 20
PANEL_HEIGHT = 7
PANEL_Y = SCREEN_HEIGHT - PANEL_HEIGHT
#message log constants
MSG_X = BAR_WIDTH + 2
MSG_WIDTH = SCREEN_WIDTH - BAR_WIDTH - 2
MSG_HEIGHT = PANEL_HEIGHT - 1
#Inventory constants
MAX_INVENTORY = 26
INVENTORY_WIDTH = 50
#Stats screen constants
LEVEL_SCREEN_WIDTH = 40
CHARACTER_SCREEN_WIDTH = 30

#parameters for dungeon generator
ROOM_MAX_SIZE = 14
ROOM_MIN_SIZE = 6
MAX_ROOMS = 60

#magic constants
HEAL_AMOUNT = 4
LIGHTNING_RANGE = 5
LIGHTNING_DAMAGE = 50
CONFUSE_DEFAULT_SPEED = 2
CONFUSE_NUM_TURNS = 2
CONFUSE_RANGE = 3
FIREBALL_RADIUS = 2
FIREBALL_DAMAGE = 15

#System values
FOV_ALGO = 0  #default FOV algorithm
FOV_LIGHT_WALLS = True  #light walls or not
TORCH_RADIUS = 6
LIMIT_FPS = 10  #10 frames-per-second maximum

#Character Progression
LEVEL_UP_BASE = 400
LEVEL_UP_FACTOR = 400

#Colours
color_dark_wall = libtcod.Color(0, 0, 50)
color_light_wall = libtcod.Color(180, 60, 50)
color_dark_ground = libtcod.Color(20, 20, 85)
color_light_ground = libtcod.Color(250, 130, 50)
color_target_ground = libtcod.light_blue #Color(255, 0, 0)


class Tile:
    #a tile of the map and its properties
    def __init__(self, blocked, block_sight = None):
        self.blocked = blocked
 
        #all tiles start untargeted
        self.targeted = False
        self.targeted_by = []

        #all tiles start unexplored
        self.explored = False
 
        #by default, if a tile is blocked, it also blocks sight
        if block_sight is None: block_sight = blocked
        self.block_sight = block_sight

    def target(self, shooter):
        self.targeted = True
        self.targeted_by.append(shooter)
        fov_recompute = True

    def untarget(self, shooter):
        self.targeted_by.remove(shooter)
        if len(self.targeted_by) == 0:
            self.targeted = False
            fov_recompute = True

class Rect:
    #a rectangle on the map. used to characterize a room.
    def __init__(self, x, y, w, h):
        self.x1 = x
        self.y1 = y
        self.x2 = x + w
        self.y2 = y + h
 
    def center(self):
        center_x = (self.x1 + self.x2) / 2
        center_y = (self.y1 + self.y2) / 2
        return (center_x, center_y)
 
    def intersect(self, other):
        #returns true if this rectangle intersects with another one
        return (self.x1 <= other.x2 and self.x2 >= other.x1 and
                self.y1 <= other.y2 and self.y2 >= other.y1)


class Object:
    #this is a generic object: the player, a monster, an item, the stairs...
    #it's always represented by a character on screen.
    def __init__(self, x, y, char, name, color, blocks=False, always_visible=False, fighter=None, ai=None, item=None, equipment=None):
        self.x = x
        self.y = y
        self.char = char
        self.name = name
        self.color = color
        self.blocks = blocks
        self.always_visible = always_visible

        self.fighter = fighter
        if self.fighter:  #Let the fighter component know who owns it
            self.fighter.owner = self

        self.ai = ai
        if self.ai:  #Let the AI component know who owns it
            self.ai.owner = self
        
        self.equipment = equipment
        if self.equipment:  #let the equipment component know who owns it
            self.equipment.owner = self
            #there must be an Item component for the equipment component to work properly
            item = Item()

        self.item = item
        if self.item:  #Let the item component know who owns it
            self.item.owner = self
 
    def move(self, dx, dy):
        #move by the given amount, if the destination is not blocked
        if not is_blocked(self.x + dx, self.y + dy):
            self.x += dx
            self.y += dy
 
    def draw(self):
        #only show if it's visible to the player
        if (libtcod.map_is_in_fov(fov_map, self.x, self.y) or (self.always_visible and map[self.x][self.y].explored)):
            #set the color and then draw the character that represents this object at its position
            libtcod.console_set_default_foreground(con, self.color)
            libtcod.console_put_char(con, self.x, self.y, self.char, libtcod.BKGND_NONE)
 
    def clear(self):
        #erase the character that represents this object
        libtcod.console_put_char(con, self.x, self.y, ' ', libtcod.BKGND_NONE)

    def move_towards(self, target_x, target_y):
        #vector from this object to the target, and distance
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        #normalize it to length 1 (preserving direction), then round it and
        #convert to integer so the movement is restricted to the map grid
        dx = int(round(dx/distance))
        dy = int(round(dy/distance))
        self.move(dx, dy)

    def distance_to(self, other):
        #return the distance to another object:
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx ** 2 + dy ** 2)

    def distance(self, x, y):
        #return the distance to some coordinates
        return math.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

    def send_to_back(self):
        global objects
        objects.remove(self)
        objects.insert(0, self)

    def get_direction(self, other):
        new_x = self.x - other.x
        new_y = self.y - other.y
        distance = math.sqrt(new_x ** 2 + new_y ** 2)
        dx = int(round(new_x/distance))
        dy = int(round(new_y/distance))
        return (dx, dy)


class Fighter:
    #combat-related properties and methods (monster, player, NPC).
    def __init__(self, hp, defense, power, xp, death_function=None):
        self.base_max_hp = hp
        self.hp = hp
        self.base_defense = defense
        self.base_power = power
        self.xp = xp
        self.death_function = death_function

    @property
    def max_hp(self):  #return actual max_hp, by summing up the bonuses from all equipped items
        bonus = sum(equipment.max_hp_bonus for equipment in get_all_equipped(self.owner))
        return self.base_max_hp + bonus

    @property
    def defense(self):  #return actual defense, by summing up the bonuses from all equipped items
        bonus = sum(equipment.defense_bonus for equipment in get_all_equipped(self.owner))
        return self.base_defense + bonus

    @property
    def power(self):  #return actual power, by summing up the bonuses from all equipped items
        bonus = sum(equipment.power_bonus for equipment in get_all_equipped(self.owner))
        return self.base_power + bonus

    

    def take_damage(self, damage):
        #apply damage if possible
        if damage > 0:
            self.hp -= damage
            if self.hp <= 0:
                self.hp = 0
                if self.owner != player:
                    player.fighter.xp += self.xp
                function = self.death_function
                if function is not None:
                    function(self.owner)

    def attack(self, target):
        #a simple formula for attack damage
        damage = self.power - target.fighter.defense

        if damage > 0:
            #make the target take some damage
            message(self.owner.name.capitalize() + ' attacks ' + target.name + ' for ' + str(damage) + ' hit points.', libtcod.light_red)
            target.fighter.take_damage(damage)
        else:
            message(self.owner.name.capitalize() + ' attacks ' + target.name + ' but it has no effect!', libtcod.lighter_red)

    def heal(self, amount):
        #heal by the given amount, without going over the maximum
        self.hp += amount
        if self.hp > self.max_hp:
            self.hp = self.max_hp

class BasicMonster:
    def __init__(self, speed=3):
        self.speed = speed
        self.counter = 0

    #AI for a basic monster.
    def take_turn(self):
        #a basic monster's interal clock ticks
        self.counter += 1
        if self.counter == self.speed:
            self.counter = 0
        else:
            return

        #a basic monster takes its turn. If you can see it, it can see you
        monster = self.owner
        if libtcod.map_is_in_fov(fov_map, monster.x, monster.y):

            #move towards player if far away
            if monster.distance_to(player) >= 2:
                monster.move_towards(player.x, player.y)

            #close enough, attack! (if the player is still alive.)
            elif player.fighter.hp > 0:
                monster.fighter.attack(player)
        else:
            x = libtcod.random_get_int(0, -1, 1)
            y = libtcod.random_get_int(0, -1, 1)
            monster.move(x, y)


class ConfusedMonster:
    def __init__(self, old_ai, num_turns=CONFUSE_NUM_TURNS):
        self.old_ai = old_ai
        self.num_turns = num_turns
        self.speed = CONFUSE_DEFAULT_SPEED
        if self.old_ai.speed:
            self.speed = self.old_ai.speed
        self.counter = 0
        if self.old_ai.counter:
            self.counter = self.old_ai.counter
            
    #AI for confused monster.
    def take_turn(self):
        if self.num_turns > 0:  #Still confused...
            #a confused monster's interal clock ticks
            self.counter += 1
            if self.counter == self.speed:
                self.counter = 0
                self.num_turns -= 1
            else:
                return

            #move in a random direction
            self.owner.move(libtcod.random_get_int(0, -1, 1), libtcod.random_get_int(0, -1, 1))
        else:  #restore the previous AI (this one will be deleted cuz no longer referenced)
            if self.old_ai.counter:
                self.old_ai.counter = self.counter
            self.owner.ai = self.old_ai
            message ('The ' + self.owner.name + ' is no longer disoriented.', libtcod.lighter_yellow)


class GatewayAI:
    def __init__(self, obj, speed=8, spawn_range=15):
        self.obj = obj
        self.speed = speed
        self.counter = 0
        self.spawn_range = spawn_range

    #AI for a basic monster.
    def take_turn(self):
        gateway = self.owner
        if gateway.distance_to(player) <= self.spawn_range:
            #a basic monster's interal clock ticks
            self.counter += 1
            if self.counter == self.speed:
                self.counter = 0
            else:
                return

            x = 0
            y = 0
            attempt = 0
            while True:
                x = gateway.x + libtcod.random_get_int(0, -1, 1)
                y = gateway.y + libtcod.random_get_int(0, -1, 1)
                if not is_blocked(x, y):
                    break
                else:
                    attempt += 1
                    if attempt == 12:
                        self.counter = self.speed - 2
                        return

            ObjectFactory.create_object(self.obj, x, y)


class GoblinKingAI:
    def __init__(self, speed=4, sub_ai=None):
        self.speed = speed
        self.counter = 0
        self.enraged = False
        self.attack_type = 0
        self.target_tiles = []
        self.target_coordinates = []

        self.sub_ai = sub_ai

    def take_turn(self):
        #secondary AI takes a turn
        if self.sub_ai:
            self.sub_ai.owner = self.owner
            self.sub_ai.take_turn()

        #the goblin king's interal clock ticks
        self.continue_attack()
        self.counter += 1
        if (self.enraged and self.counter == self.speed - 1) or self.counter == self.speed:
            if self.counter == self.speed:
                self.counter = 0
            if self.enraged != True and self.owner.fighter.hp < self.owner.fighter.max_hp/2:
                self.enraged = True
                self.speed += 1
                message('the ' + self.owner.name + ' has become enraged!', libtcod.light_red)
        else:
            return

        #The goblin king takes his turn. He moves and attacks.
        monster = self.owner
        if libtcod.map_is_in_fov(fov_map, monster.x, monster.y):
            #move towards player if far away
            if monster.distance_to(player) >= 2:
                monster.move_towards(player.x, player.y)
            #attack
            self.attack()

    def attack(self):
        monster = self.owner

        if self.attack_type == 0:
            self.attack_type = libtcod.random_get_int(0, 1, 4)

            #BASIC ATTACK
            if self.attack_type == 1:
                if monster.distance_to(player) == 1:
                    message('The ' + monster.name + ' charges at you!', libtcod.light_blue)
                    monster.fighter.attack(player)
                else:
                    message('The ' + monster.name + ' swings his fist, but you were out of range.', libtcod.light_blue)

            #LINE/ANGLE IN FRONT ATTACK
            elif self.attack_type == 2:
                (new_x, new_y) = monster.get_direction(player)
                x = monster.x - new_x
                y = monster.y - new_y

                if new_x == 0:
                    self.target_tiles.append(map[x-1][y])
                    self.target_tiles.append(map[x][y])
                    self.target_tiles.append(map[x+1][y])
                    self.target_coordinates.append((x-1, y))
                    self.target_coordinates.append((x, y))
                    self.target_coordinates.append((x+1, y))
                elif new_y == 0:
                    self.target_tiles.append(map[x][y-1])
                    self.target_tiles.append(map[x][y])
                    self.target_tiles.append(map[x][y+1])
                    self.target_coordinates.append((x, y-1))
                    self.target_coordinates.append((x, y))
                    self.target_coordinates.append((x, y+1))
                else:
                    if new_x > 0:
                        if new_y > 0:
                            self.target_tiles.append(map[x+1][y])
                            self.target_tiles.append(map[x][y])
                            self.target_tiles.append(map[x][y+1])
                            self.target_coordinates.append((x+1, y))
                            self.target_coordinates.append((x, y))
                            self.target_coordinates.append((x, y+1))
                        else:
                            self.target_tiles.append(map[x+1][y])
                            self.target_tiles.append(map[x][y])
                            self.target_tiles.append(map[x][y-1])
                            self.target_coordinates.append((x+1, y))
                            self.target_coordinates.append((x, y))
                            self.target_coordinates.append((x, y-1))
                    else:
                        if new_y > 0:
                            self.target_tiles.append(map[x-1][y])
                            self.target_tiles.append(map[x][y])
                            self.target_tiles.append(map[x][y+1])
                            self.target_coordinates.append((x-1, y))
                            self.target_coordinates.append((x, y))
                            self.target_coordinates.append((x, y+1))
                        else:
                            self.target_tiles.append(map[x-1][y])
                            self.target_tiles.append(map[x][y])
                            self.target_tiles.append(map[x][y-1])
                            self.target_coordinates.append((x-1, y))
                            self.target_coordinates.append((x, y))
                            self.target_coordinates.append((x, y-1))

                for tile in self.target_tiles:
                    tile.target(monster)
                message('The ' + monster.name + ' prepares to swing his hammer!', color_target_ground)

            #STRAIGHT LINE TOWARD PLAYER ATTACK
            elif self.attack_type == 3:
                (x, y) = monster.get_direction(player)
                for i in range(1, 4):
                    self.target_tiles.append(map[monster.x - x * i][monster.y - y * i])

                for tile in self.target_tiles:
                    tile.target(monster)
                message('The ' + monster.name + ' lifts his hammer over his head!', color_target_ground)

            #LINE OVERTOP PLAYER
            elif self.attack_type == 4:
                if monster.distance_to(player) <= 4:
                    x = player.x
                    y = player.y

                    if libtcod.random_get_int(0, 0, 1) == 1:
                        self.target_tiles.append(map[x-1][y])
                        self.target_tiles.append(map[x][y])
                        self.target_tiles.append(map[x+1][y])
                        self.target_coordinates.append((x-1, y))
                        self.target_coordinates.append((x, y))
                        self.target_coordinates.append((x+1, y))
                    else:
                        self.target_tiles.append(map[x][y-1])
                        self.target_tiles.append(map[x][y])
                        self.target_tiles.append(map[x][y+1])
                        self.target_coordinates.append((x, y-1))
                        self.target_coordinates.append((x, y))
                        self.target_coordinates.append((x, y+1))

                    for tile in self.target_tiles:
                        tile.target(monster)
                    message('The ' + monster.name + ' throws his hammer into the air!', color_target_ground)

    def continue_attack(self):
        if self.attack_type > 1:
            flag = False
            monster = self.owner

            #Untarget tiles
            for tile in self.target_tiles:
                tile.untarget(monster)

            for i in range(len(self.target_tiles)):
                self.target_tiles.pop()

            #Apply damage to player if they're in any of the targeted spaces
            for (x, y) in self.target_coordinates:
                if player.x == x and player.y == y:
                        monster.fighter.attack(player)
                        flag = True
            for i in range(len(self.target_coordinates)):
                self.target_coordinates.pop()

            if not flag:
                message('The ' + monster.name + ' attacks, but he missed!', libtcod.light_blue)

        self.attack_type = 0


class RangedAI:
    def __init__(self, speed=4, shoot_range=TORCH_RADIUS):
        self.speed = speed
        self.counter = 0
        self.shoot_range = shoot_range
        self.target_tile = None
        self.target_x = -1
        self.target_y = -1

    def take_turn(self):
        #a ranged monster's interal clock ticks
        self.counter += 1
        if self.counter >= self.speed - 1:
            if self.counter == self.speed:
                self.counter = 0
        else:
            return

        #a ranged monster takes its turn. If you are in range, it will shoot you
        monster = self.owner

        if player.fighter.hp > 0:
            if self.counter == self.speed - 1:
                if self.owner.distance_to(player) <= self.shoot_range:
                    self.target_x = player.x
                    self.target_y = player.y
                    self.target_tile = map[self.target_x][self.target_y]
                    self.target_tile.target(monster)
                    message(monster.name + ' takes aim!', color_target_ground)
            else:
                if self.target_tile:
                    self.target_tile.untarget(monster)
                    self.target_tile = None
                    if player.x == self.target_x and player.y == self.target_y:
                        monster.fighter.attack(player)
                    else:
                        message('The ' + monster.name + ' missed!', libtcod.light_blue)


class Item:
    def __init__(self, use_function=None):
        self.use_function = use_function

    #an item that can be picked up and used.
    def pick_up(self):
        #add to the player's inventory and remove from the map
        if len(inventory) >= MAX_INVENTORY:
            message('Your inventory is full, cannot pick up ' + self.owner.name + '.', libtcod.red)
        else:
            inventory.append(self.owner)
            objects.remove(self.owner)
            message('You picked up a ' + self.owner.name + '!', libtcod.green)

            #special case: automatically equip, if the corresponding equipment slot is unused
            equipment = self.owner.equipment
            if equipment and get_equipped_in_slot(equipment.slot) is None:
                equipment.equip()

    def use(self):
        #equip/dequip equipment on use
        if self.owner.equipment:
            self.owner.equipment.toggle_equip()
        #just call the "use_function" if it is defined
        elif self.use_function is None:
            message('The ' + self.owner.name + ' cannot be used.')
        else:
            if self.use_function() != 'cancelled':
                inventory.remove(self.owner)  #destroy after use, unless it was cancelled for some reason

    def drop(self):
        #first, dequip if it is equipped equipment
        if self.owner.equipment and self.owner.equipment.is_equipped:
            self.owner.equipment.dequip()
            if self.owner.fighter.hp > self.owner.fighter.max_hp:
                self.owner.fighter.hp = self.owner.fighter.max_hp

        #add to the map and remove from the player's inventory.
        #also, place it at the player's coordinates
        objects.append(self.owner)
        inventory.remove(self.owner)
        self.owner.x = player.x
        self.owner.y = player.y
        message('You dropped a ' + self.owner.name + '.', self.owner.color)


class Equipment:
    #an object that can be equipped, yielding bonuses. Automatically adds the Item component
    def __init__(self, slot, power_bonus=0, defense_bonus=0, max_hp_bonus=0):
        self.slot = slot
        self.is_equipped = False
        self.power_bonus = power_bonus
        self.defense_bonus = defense_bonus
        self.max_hp_bonus = max_hp_bonus

    def toggle_equip(self):  #toggle equip/dequip status
        if self.is_equipped:
            self.dequip()
        else:
            self.equip()

    def equip(self):
        #dequip old equipment
        old_equipment = get_equipped_in_slot(self.slot)
        if old_equipment is not None:
            old_equipment.dequip()

        #equip object and show a message about it
        self.is_equipped = True
        message('Equipped ' + self.owner.name + ' on ' + self.slot + '.', libtcod.light_green)

    def dequip(self):
        #dequip object and show a message about it
        if not self.is_equipped: return
        self.is_equipped = False
        message('Dequipped ' + self.owner.name + ' from ' + self.slot + '.', libtcod.light_green)


class ObjectFactory:
    @staticmethod
    def append_front(obj):
        objects.append(obj)

    @staticmethod
    def append_back(obj):
        objects.append(obj)
        obj.send_to_back()

    @staticmethod
    def create_object(obj, x, y):
        global player

        if obj == 'player':
            fighter_component = Fighter(hp=30, defense=2, power=5, xp=0, death_function=player_death)
            player = Object(x, y, '@', 'player', libtcod.white, blocks=True, fighter=fighter_component)
            ObjectFactory.append_front(player)  #append to objects

    ### MONSTERS ###

        elif obj == 'goblin':
            fighter_component = Fighter(hp=10, defense=0, power=3, xp=10, death_function=monster_death)
            ai_component = BasicMonster(speed=2)
            monster = Object(x, y, 'g', 'goblin', libtcod.dark_red, blocks=True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'goblinX2':
            #Create a goblin
            ObjectFactory.create_object('goblin', x, y)  #first goblin

            #Create a second globin
            x2 = 0
            y2 = 0
            while True:
                x2 = libtcod.random_get_int(0, x - 1, x + 1)
                y2 = libtcod.random_get_int(0, y - 1, y + 1)
                if (x2 != x or y2 != y) and not is_blocked(x2, y2):
                    break
            ObjectFactory.create_object('goblin', x2, y2) #second goblin

        elif obj == 'orc':
            #create a an orc
            fighter_component = Fighter(hp=20, defense=0, power=4, xp=20, death_function=monster_death)
            ai_component = BasicMonster()
            monster = Object(x, y, 'o', 'orc', libtcod.desaturated_green, blocks=True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'troll':
            #Create a troll
            fighter_component = Fighter(hp=40, defense=1, power=10, xp=50, death_function=monster_death)
            ai_component = BasicMonster(speed=4)
            monster = Object(x, y, 'T', 'troll', libtcod.darker_green, blocks=True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'nightmare':
            #Create a nightmare
            fighter_component = Fighter(hp=100, defense=10, power=10, xp=1000, death_function=monster_death)
            ai_component = BasicMonster(speed=1)
            monster = Object(x, y, 'N', 'nightmare', libtcod.darker_flame, blocks=True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'fletchling':
            #Create a fletchling
            fighter_component = Fighter(hp=2, defense=5, power=7, xp=0, death_function=monster_death)
            ai_component = BasicMonster(speed=2)
            monster = Object(x, y, 'f', 'fletchling', libtcod.dark_flame, blocks = True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'fletchling-gateway':
            fighter_component = Fighter(hp=75, defense=0, power=0, xp=1000, death_function=gateway_death)
            ai_component = GatewayAI('fletchling')
            monster = Object(x, y, 'G', 'fletchling gateway', libtcod.dark_flame, blocks = True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'goblin-prince':
            fighter_component = Fighter(hp=200, defense=3, power=10, xp=1500, death_function=monster_death)
            sub_ai_component = RangedAI(shoot_range=8)
            ai_component = GoblinKingAI(sub_ai = sub_ai_component)
            monster = Object(x, y, 'P', 'goblin prince', libtcod.black, blocks = True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

        elif obj == 'archer':
            fighter_component = Fighter(hp=60, defense=2, power=10, xp=300, death_function=monster_death)
            ai_component = RangedAI()
            monster = Object(x, y, 'a', 'archer', libtcod.white, blocks = True, fighter=fighter_component, ai=ai_component)

        elif obj == 'fast-archer':
            fighter_component = Fighter(hp=100, defense=2, power=10, xp=500, death_function=monster_death)
            ai_component-RangedAI(speed=2)
            monster = Object(x, y, 'A', 'elite archer', libtcod.lighter_grey, blocks = True, fighter=fighter_component, ai=ai_component)

    ## BOSSES ###
        elif obj == 'goblin-king':
            fighter_component = Fighter(hp=400, defense=4, power=12, xp=5000, death_function=boss_death)
            sub_ai_component = RangedAI(shoot_range=15)
            ai_component = GoblinKingAI(sub_ai=sub_ai_component)
            monster = Object(x, y, 'K', 'Goblin King', libtcod.black, blocks = True, fighter=fighter_component, ai=ai_component)
            ObjectFactory.append_front(monster)  #append to objects

    ### ITEMS ###

        elif obj == 'heal':
            item_component = Item(use_function=cast_heal)
            item = Object(x, y, '!', 'first-aid kit', libtcod.light_chartreuse, item=item_component)
            ObjectFactory.append_back(item)  #append to objects

        elif obj == 'confuse':
            #create a confusion spell
            item_component = Item(use_function=cast_confuse)
            item = Object(x, y, '#', 'flashbang',libtcod.light_yellow, item=item_component)
            ObjectFactory.append_back(item)  #append to objects

        elif obj == 'fireball':
            #create a fireball spell
            item_component = Item(use_function=cast_fireball)
            item = Object(x, y, '#', 'cloud of poison',libtcod.light_green, item=item_component)
            ObjectFactory.append_back(item)  #append to objects

        elif obj == 'lightning':
            #create a lightning bolt spell
            item_component = Item(use_function=cast_lightning)
            item = Object(x, y, '#', 'ray gun', libtcod.light_blue, item=item_component)
            ObjectFactory.append_back(item)  #append to objects

    ### EQUIPMENT ###

        elif obj == 'petty-sword':
            #create a sword
            equipment_component = Equipment(slot='right hand', power_bonus=2)
            item = Object(x, y, '/', 'rusty pole', libtcod.darkest_orange, equipment=equipment_component)
            ObjectFactory.append_back(item)  #append to objects

        elif obj == 'petty-shield':
            #create a shield
            equipment_component = Equipment(slot='left hand', defense_bonus=2)
            item = Object(x, y, '+', 'metal plate', libtcod.silver, equipment=equipment_component)
            ObjectFactory.append_back(item)  #append to objects

        elif obj == 'petty-breastplate':
            #create a breastplate
            equipment_component = Equipment(slot='chest', max_hp_bonus=30)
            item = Object(x, y, '&', 'thick vest', libtcod.sepia, equipment=equipment_component)
            ObjectFactory.append_back(item)  #append to objects

    ### STAIRS ###

        elif obj == 'stairs':
            global stairs
            #create stairs
            stairs = Object(x, y, '<', 'stairs', libtcod.white, always_visible=True)
            ObjectFactory.append_back(stairs)  #append to objects

        elif obj == 'late-stairs':
            global stairs
            #create stairs later in the game
            stairs = Object(x, y, '<', 'stairs', libtcod.white, always_visible=True)
            ObjectFactory.append_front(stairs)  #append to objects


def is_blocked(x, y):
    #first test the map tile
    if map[x][y].blocked:
        return True

    #now check for any blocking objects
    for object in objects:
        if object.blocks and object.x == x and object.y == y:
            return True

    return False

def get_all_equipped(obj):  #returns a list of equipped items
    if obj == player:
        equipped_list = []
        for item in inventory:
            if item.equipment and item.equipment.is_equipped:
                equipped_list.append(item.equipment)
        return equipped_list
    else:
        return []  #other objects have no equipment

def get_equipped_in_slot(slot):  #returns the equipment in a slot, or None if it's empty
    for obj in inventory:
        if obj.equipment and obj.equipment.slot == slot and obj.equipment.is_equipped:
            return obj.equipment
    return None

def create_room(room):
    global map
    #go through the tiles in the rectangle and make them passable
    for x in range(room.x1 + 1, room.x2):
        for y in range(room.y1 + 1, room.y2):
            map[x][y].blocked = False
            map[x][y].block_sight = False
 
def create_h_tunnel(x1, x2, y):
    global map
    #horizontal tunnel. min() and max() are used in case x1>x2
    for x in range(min(x1, x2), max(x1, x2) + 1):
        map[x][y].blocked = False
        map[x][y].block_sight = False
 
def create_v_tunnel(y1, y2, x):
    global map
    #vertical tunnel
    for y in range(min(y1, y2), max(y1, y2) + 1):
        map[x][y].blocked = False
        map[x][y].block_sight = False

def make_boss_map():
    global map, objects

    #the list of objects with player in it
    objects = [player]

    #fill map with "blocked" tiles
    map = [[ Tile(True)
        for y in range(MAP_HEIGHT) ]
            for x in range(MAP_WIDTH) ]
 
    num_rooms = 0
    rooms = []

    #entrance room
    new_room = Rect(MAP_WIDTH/2 - ROOM_MIN_SIZE/2, MAP_HEIGHT - ROOM_MIN_SIZE - 2, ROOM_MIN_SIZE, ROOM_MIN_SIZE)
    create_room(new_room)
    (new_x, new_y) = new_room.center()
    rooms.append(new_room)

    #this is the first room, where the player starts at
    player.x = new_x
    player.y = new_y
    num_rooms += 1

    #This is the main boss room
    new_room = Rect(MAP_WIDTH/2 - (ROOM_MAX_SIZE + 4)/2, MAP_HEIGHT - ROOM_MIN_SIZE - 8 - ROOM_MAX_SIZE, ROOM_MAX_SIZE + 4, ROOM_MAX_SIZE + 4)
    create_room(new_room)
    (new_x, new_y) = new_room.center()
    (prev_x, prev_y) = rooms[num_rooms-1].center()
    create_v_tunnel(prev_y, new_y, new_x)
    rooms.append(new_room)

    ObjectFactory.create_object('goblin-king', new_x, new_y)
    ObjectFactory.create_object('fletchling-gateway', new_room.x1 + 1, new_room.y1 + 1)
    ObjectFactory.create_object('fletchling-gateway', new_room.x2 - 1, new_room.y1 + 1)
    ObjectFactory.create_object('fletchling-gateway', new_room.x1 + 1, new_room.y2 - 1)
    ObjectFactory.create_object('fletchling-gateway', new_room.x2 - 1, new_room.y2 - 1)
    num_rooms += 1

    #This is the left side room
    new_room = Rect(MAP_WIDTH/2 - (ROOM_MAX_SIZE + 4)/2 - 4 - ROOM_MIN_SIZE, MAP_HEIGHT - ROOM_MIN_SIZE - 8 - ROOM_MAX_SIZE/2, ROOM_MIN_SIZE, ROOM_MIN_SIZE)
    create_room(new_room)
    (new_x, new_y) = new_room.center()
    (prev_x, prev_y) = rooms[num_rooms-1].center()
    create_h_tunnel(prev_x, new_x, new_y)
    rooms.append(new_room)

    ObjectFactory.create_object('troll', new_x, new_y - 1)
    ObjectFactory.create_object('troll', new_x - 1, new_y)
    ObjectFactory.create_object('troll', new_x, new_y + 1)
    num_rooms += 1
    
    #This is the right side room
    new_room = Rect(MAP_WIDTH/2 + (ROOM_MAX_SIZE + 4)/2 + 4, MAP_HEIGHT - ROOM_MIN_SIZE - 8 - ROOM_MAX_SIZE/2, ROOM_MIN_SIZE, ROOM_MIN_SIZE)
    create_room(new_room)
    (new_x, new_y) = new_room.center()
    (prev_x, prev_y) = rooms[num_rooms-1].center()
    create_h_tunnel(prev_x, new_x, new_y)
    rooms.append(new_room)

    ObjectFactory.create_object('troll', new_x, new_y - 1)
    ObjectFactory.create_object('troll', new_x + 1, new_y)
    ObjectFactory.create_object('troll', new_x, new_y + 1)
    num_rooms += 1

def make_map():
    global map, objects, stairs
 
    #the list of objects with player in it
    objects = [player]

    #fill map with "blocked" tiles
    map = [[ Tile(True)
        for y in range(MAP_HEIGHT) ]
            for x in range(MAP_WIDTH) ]
 
    rooms = []
    num_rooms = 0
 
    for r in range(MAX_ROOMS):
        #random width and height
        w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        #random position without going out of the boundaries of the map
        x = libtcod.random_get_int(0, 0, MAP_WIDTH - w - 1)
        y = libtcod.random_get_int(0, 0, MAP_HEIGHT - h - 1)
 
        #"Rect" class makes rectangles easier to work with
        new_room = Rect(x, y, w, h)
 
        #run through the other rooms and see if they intersect with this one
        failed = False
        for other_room in rooms:
            if new_room.intersect(other_room):
                failed = True
                break
 
        if not failed:
            #this means there are no intersections, so this room is valid
 
            #"paint" it to the map's tiles
            create_room(new_room)
 
            #center coordinates of new room, will be useful later
            (new_x, new_y) = new_room.center()
 
            if num_rooms == 0:
                #this is the first room, where the player starts at
                player.x = new_x
                player.y = new_y
            else:
                #all rooms after the first:
                #connect it to the previous room with a tunnel
 
                #center coordinates of previous room
                (prev_x, prev_y) = rooms[num_rooms-1].center()
 
                #draw a coin (random number that is either 0 or 1)
                if libtcod.random_get_int(0, 0, 1) == 1:
                    #first move horizontally, then vertically
                    create_h_tunnel(prev_x, new_x, prev_y)
                    create_v_tunnel(prev_y, new_y, new_x)
                else:
                    #first move vertically, then horizontally
                    create_v_tunnel(prev_y, new_y, prev_x)
                    create_h_tunnel(prev_x, new_x, new_y)
 
            #add some contents to this room, such as monsters
            place_objects(new_room)

            #finally, append the new room to the list
            rooms.append(new_room)
            num_rooms += 1

    #create stairs at the center of the Last room
    ObjectFactory.create_object('stairs', new_x, new_y)

def place_objects(room):
    #choose random number of monsters
    max_monsters = from_dungeon_level([[2, 1], [3, 4], [5, 6], [7, 9], [0, 10]])

    #chance of each monster
    monster_chances = {}
    monster_chances['goblin'] =    from_dungeon_level([[80, 1], [40, 3], [20, 5], [0, 8]])
    monster_chances['goblinX2'] =  from_dungeon_level([         [20, 3], [30, 5], [30, 8]])
    monster_chances['orc'] =       from_dungeon_level([[19, 1], [25, 3], [29, 5], [34, 8]])
    monster_chances['troll'] =     from_dungeon_level([         [14, 3], [19, 5], [33, 8]])
    monster_chances['nightmare'] = from_dungeon_level([[1, 1],           [2, 5],  [3, 8]])

    #maximum number of items per room
    max_items = from_dungeon_level([[1, 1], [2, 4], [3, 7], [0, 10]])

    #chances of each item (by default they have a chance of 0 at level 1, which then goes up
    item_chances = {}
    item_chances['heal'] =      from_dungeon_level([[46, 1], [50, 2], [50, 4], [20, 6]])
    item_chances['lightning'] = from_dungeon_level([[4, 1],  [3, 2],  [2, 4],  [1, 6]])
    item_chances['confuse'] =   from_dungeon_level([         [22, 2], [28, 4], [30, 6]])
    item_chances['fireball'] =  from_dungeon_level([                  [20, 4], [49, 6]])
    item_chances['petty-sword'] = 1
    item_chances['petty-shield'] = 1
    item_chances['petty-breastplate'] = 1

    #randomize value of monsters per room
    num_monsters = libtcod.random_get_int(0, 0, max_monsters)

    for i in range(num_monsters):
        #choose random spot for this monster
        x = 0
        y = 0
        while True:
            x = libtcod.random_get_int(0, room.x1+1, room.x2-1)
            y = libtcod.random_get_int(0, room.y1+1, room.y2-1)
            if not is_blocked(x, y):
                break
        choice = random_choice(monster_chances)
        ObjectFactory.create_object(choice, x, y)
            

    #choose random number of items
    num_items = libtcod.random_get_int(0, 0, max_items)

    for i in range(num_items):
        while True:
            #choose random spot for this item
            x = libtcod.random_get_int(0, room.x1 + 1, room.x2 - 1)
            y = libtcod.random_get_int(0, room.y1 + 1, room.y2 - 1)
            if not is_blocked(x, y):
                break;

        choice = random_choice(item_chances)
        ObjectFactory.create_object(choice, x, y)

def random_choice(chances_dict):
    #choose one option from dictionary of chances, returning its key
    chances = chances_dict.values()
    strings = chances_dict.keys()
    return strings[random_choice_index(chances)]

def random_choice_index(chances):  #choose one option from list of chances, returning its index
    #the dice will land on some number between 1 and the sum of the chances
    dice = libtcod.random_get_int(0, 1, sum(chances))

    #go through all chances, keeping the sum so far
    running_sum = 0
    choice = 0
    for w in chances:
        running_sum += w

        #see if the dice landed in the part that corresponds to this choice
        if dice <= running_sum:
            return choice
        choice += 1

def from_dungeon_level(table):
    #returns a value that depends on level. The table specifies what value occurs after each level
    #default is 0
    for (value, level) in reversed(table):
        if dungeon_level >= level:
            return value
    return 0

def render_bar(x, y, total_width, name, value, maximum, bar_color, back_color):
    #render a bar (HP, experience, etc). First calculate the width of the bar
    bar_width = int(float(value) / maximum * total_width)

    #render the background first
    libtcod.console_set_default_background(panel, back_color)
    libtcod.console_rect(panel, x, y, total_width, 1, False, libtcod.BKGND_SCREEN)

    #now render the bar on top
    libtcod.console_set_default_background(panel, bar_color)
    if bar_width > 0:
        libtcod.console_rect(panel, x, y, bar_width, 1, False, libtcod.BKGND_SCREEN)

    #finally, some centered text with the values
    libtcod.console_set_default_foreground(panel, libtcod.white)
    libtcod.console_print_ex(panel, x + total_width / 2, y, libtcod.BKGND_NONE, libtcod.CENTER, name + ': ' + str(value) + '/' + str(maximum))

def get_names_under_mouse():
    global mouse
    #return a string with the names of all objects under the mouse

    (x, y) = (mouse.cx, mouse.cy)

    #create a list with the names of all objects at the mouse's coordinates and in FOV
    names = [obj.name for obj in objects
        if obj.x == x and obj.y == y and libtcod.map_is_in_fov(fov_map, obj.x, obj.y)]
    names = ', '.join(names)

    return names.capitalize()

def render_all():
    global fov_map, color_dark_wall, color_light_wall
    global color_dark_ground, color_light_ground
    global fov_recompute
 
    #just testing
    fov_recompute = True
    if fov_recompute:
        #recompute FOV if needed (the player moved or something)
        fov_recompute = False
        libtcod.map_compute_fov(fov_map, player.x, player.y, TORCH_RADIUS, FOV_LIGHT_WALLS, FOV_ALGO)
 
        #go through all tiles, and set their background color according to the FOV
        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                visible = libtcod.map_is_in_fov(fov_map, x, y)
                wall = map[x][y].block_sight
                if not visible:
                    #if it's not visible right now, the player can only see it if it's explored
                    if map[x][y].explored:
                        if wall:
                            libtcod.console_set_char_background(con, x, y, color_dark_wall, libtcod.BKGND_SET)
                        else:
                            libtcod.console_set_char_background(con, x, y, color_dark_ground, libtcod.BKGND_SET)
                else:
                    #it's visible
                    if wall:
                        libtcod.console_set_char_background(con, x, y, color_light_wall, libtcod.BKGND_SET)
                    else:
                        if map[x][y].targeted:
                            libtcod.console_set_char_background(con, x, y, color_target_ground, libtcod.BKGND_SET )
                        else:
                            libtcod.console_set_char_background(con, x, y, color_light_ground, libtcod.BKGND_SET)
                    #since it's visible, explore it
                    map[x][y].explored = True
 
    #draw all objects in the list
    for object in objects:
        object.draw()
    player.draw()
 
    #blit the contents of "con" to the root console
    libtcod.console_blit(con, 0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, 0, 0)

    #prepare to render the GUI panel
    libtcod.console_set_default_background(panel, libtcod.black)
    libtcod.console_clear(panel)

    #show the player's stats
    render_bar(1, 1, BAR_WIDTH, 'hp', player.fighter.hp, player.fighter.max_hp, libtcod.light_red, libtcod.darker_red)

    #show the current dungeon level
    libtcod.console_print_ex(panel, 1, 3, libtcod.BKGND_NONE, libtcod.LEFT, 'Test #' + str(dungeon_level))
    (map_count, map_explored) = count_remaining_tiles()
    #show the amount of exploration remaining in the level
    libtcod.console_print_ex(panel, 1, 4, libtcod.BKGND_NONE, libtcod.LEFT, 'Explored: ' + str(map_explored) + '/' + str(map_count))
    #show the amount of enemies remaining in the level
    libtcod.console_print_ex(panel, 1, 5, libtcod.BKGND_NONE, libtcod.LEFT, 'Remaining enemies: ' + str(count_remaining_enemies()))
    #show the amount of enemies remaining in the level
    libtcod.console_print_ex(panel, 1, 6, libtcod.BKGND_NONE, libtcod.LEFT, 'Remaining items: ' + str(count_remaining_items()))

    #display names of objects under the mouse
    libtcod.console_set_default_foreground(panel, libtcod.light_gray)
    libtcod.console_print_ex(panel, 1, 0, libtcod.BKGND_NONE, libtcod.LEFT, get_names_under_mouse())

    #print the game messages, one line at a time
    y = 1
    for (line, color) in game_msgs:
        libtcod.console_set_default_foreground(panel, color)
        libtcod.console_print_ex(panel, MSG_X, y, libtcod.BKGND_NONE, libtcod.LEFT, line)
        y += 1

    #blit the contents of "panel" to the root console
    libtcod.console_blit(panel, 0, 0, SCREEN_WIDTH, PANEL_HEIGHT, 0, 0, PANEL_Y)

def message(new_msg, color=libtcod.white):
    global game_msgs
    #split the message if necessary, among multiple lines
    new_msg_lines = textwrap.wrap(new_msg, MSG_WIDTH)

    for line in new_msg_lines:
        #if the buffer is full, remove the first line to make room for the new one
        if len(game_msgs) == MSG_HEIGHT:
            del game_msgs[0]

        #add the new line as a tuple, with the text and the color
        game_msgs.append( (line, color) )

def player_move_or_attack(dx, dy):
    global fov_recompute

    #the coordinates the player is moving to/attacking
    x = player.x + dx
    y = player.y + dy

    #try to find an attackable object there
    target = None
    for object in objects:
        if object.fighter and object.x == x and object.y == y:
            target = object
            break

    #attack if target found, move otherwise
    if target is not None:
        player.fighter.attack(target)
    else:
        player.move(dx, dy)
        fov_recompute = True

def check_level_up():
    #see if the player's experience is enough to level-up
    level_up_xp = LEVEL_UP_BASE + (player.level - 1) * LEVEL_UP_FACTOR
    while player.fighter.xp >= level_up_xp:
        #it is! Level up
        player.level += 1
        player.fighter.xp -= level_up_xp
        level_up_xp = LEVEL_UP_BASE + (player.level - 1) * LEVEL_UP_FACTOR
        message("You're making things interesting, Runner! You've become level " + str(player.level) + '.', libtcod.yellow)

        choice = None
        while choice == None:  #keep asking until a choice is made
            choice = menu('For your efforts, we will give you one reward. Choose wisely:\n',
                ['Medal of Survival (+15 Max HP, +10 HP)',
                'Medal of Force (+1 attack)',
                'Medal of Protection (+1 defense)',
                'Ray Gun x2'],
                LEVEL_SCREEN_WIDTH)

            if choice == 0:
                player.fighter.base_max_hp += 15
                player.fighter.hp += 10
                message('You received a medal of survival!', libtcod.lighter_green)
            elif choice == 1:
                player.fighter.base_power += 1
                message('You received a medal of force!', libtcod.lighter_red)
            elif choice == 2:
                player.fighter.base_defense += 1
                message('You received a medal of protection!', libtcod.lighter_orange)
            elif choice == 3:
                if len(inventory) >= MAX_INVENTORY - 2:
                    message('You do not have room in your inventory.', libtcod.red)
                    choice = None
                else:
                    item_component = Item(use_function=cast_lightning)
                    item = Object(0, 0, '#', 'ray gun (1 shot)', libtcod.lighter_blue, item=item_component)
                    inventory.append(item)

                    item_component2 = Item(use_function=cast_lightning)
                    item2 = Object(0, 0, '#', 'ray gun (1 shot)', libtcod.lighter_blue, item=item_component2)
                    inventory.append(item2)
    
                    message('You received two ray guns!', libtcod.lighter_blue)

def menu(header, options, width):
    if len(options) > MAX_INVENTORY: raise ValueError('Cannot have a menu with more than ' + str(MAX_INVENTORY) + ' options.')

    #calculate total height for the header (after auto-wrap) and one Line per option
    header_height = libtcod.console_get_height_rect(con, 0, 0, width, SCREEN_HEIGHT, header)
    if header == '':
        header_height = 0
    height = len(options) + header_height

    #create an off-screen console that represents the menu's window
    window = libtcod.console_new(width, height)

    #print the header, with auto-wrap
    libtcod.console_set_default_foreground(window, libtcod.white)
    libtcod.console_print_rect_ex(window, 0, 0, width, height, libtcod.BKGND_NONE, libtcod.LEFT, header)

    #print all the options
    y = header_height
    letter_index = ord('a')
    for option_text in options:
        text = '(' + chr(letter_index) + ')' + option_text
        libtcod.console_print_ex(window, 0, y, libtcod.BKGND_NONE, libtcod.LEFT, text)
        y += 1
        letter_index += 1

    #blit the contents of "window" to the root console
    x = SCREEN_WIDTH/2 - width/2
    y = SCREEN_HEIGHT/2 - height/2
    libtcod.console_blit(window, 0, 0, width, height, 0, x, y, 1.0, 0.7)

    libtcod.console_flush()
    key = libtcod.console_wait_for_keypress(True)

    if key.vk == libtcod.KEY_ENTER and key.lalt:
        #Alt+Enter: toggle fullscreen
        libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())

    #convert ASCII code to an index; if it corresponds to an ioon, return it
    index = key.c - ord('a')
    if index >= 0 and index <= len(options): return index
    return None

def msgbox(text, width=50):
    menu(text, [], width)

def inventory_menu(header):
    #show a menu with each item of the inventory as an option
    if len(inventory) == 0:
        options = ['Inventory is empty.']
    else:
        options = []
        for item in inventory:
            text = item.name
            #show additional information, in case it's equipped
            if item.equipment and item.equipment.is_equipped:
                text = text + ' (on ' + item.equipment.slot + ')'
            options.append(text)

    index = menu(header, options, INVENTORY_WIDTH)

    #if an item was chosen, return it
    if index is None or len(inventory) == 0: return index
    return inventory[index].item

def count_remaining_items():
    count = 0
    for obj in objects:
        if obj.item:
            count += 1
    return count

def count_remaining_enemies():
    count = 0
    for obj in objects:
        if obj.fighter and obj != player:
            count += 1
    return count

def count_remaining_tiles():
    count_map = 0
    count_explored = 0
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            tile = map[x][y]
            if not tile.blocked:
                count_map += 1
                if tile.explored:
                    count_explored += 1
    return (count_map, count_explored)

def handle_keys():
    global key
 
    if key.vk == libtcod.KEY_ENTER and key.lalt:
        #Alt+Enter: toggle fullscreen
        libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())
 
    elif key.vk == libtcod.KEY_ESCAPE:
        return 'exit'  #exit game
 
    if game_state == 'playing':
        #movement keys
        if key.vk == libtcod.KEY_UP:
            player_move_or_attack(0, -1)

        elif key.vk == libtcod.KEY_DOWN:
            player_move_or_attack(0, 1)

        elif key.vk == libtcod.KEY_LEFT:
            player_move_or_attack(-1, 0)

        elif key.vk == libtcod.KEY_RIGHT:
            player_move_or_attack(1, 0)
        else:
            #test for other keys
            key_char = chr(key.c)

            if key_char == 'g':
                #pick up an item
                for object in objects:  #look for an item in the player's tile
                    if object.x == player.x and object.y == player.y and object.item:
                        object.item.pick_up()
                        break
            elif key_char == 'i':
                #show the inventory
                chosen_item = inventory_menu('Press the key next to an item to use it, or any other to cancel.\n')
                if chosen_item is not None:
                    chosen_item.use()
            elif key_char == 'd':
                #show the inventory; if an item is selected, drop it
                chosen_item = inventory_menu('Press the key next to an item to drop it, or any other to cancel.\n')
                if chosen_item is not None:
                    chosen_item.drop()
            elif key_char == '.':
                #go down stairs, if the player is on them
                if stairs.x == player.x and stairs.y == player.y:
                    next_level()
            elif key_char == 'c':
                #show character information
                level_up_xp = LEVEL_UP_BASE + (player.level - 1) * LEVEL_UP_FACTOR
                msgbox('Runner #43\n\nLevel:' + str(player.level) + '\nExperience: ' + str(player.fighter.xp) + '/' + str(level_up_xp) + '\nMaximum HP: ' + str(player.fighter.max_hp) + '\nAttack: ' + str(player.fighter.power) + '\nDefense: ' + str(player.fighter.defense), CHARACTER_SCREEN_WIDTH)

            return 'didnt-take-turn' #rule for turn-based

def player_death(player):
    #the game ended!
    global game_state
    message('You died!', libtcod.dark_yellow)
    game_state = 'dead'

    #for added effect, transform the player into a corpse!
    player.char = '%'
    player.colour = libtcod.dark_red

def monster_death(monster):
    #transform it into a nasty corpse! it doesn't block, can't be
    #attacked, and doesn't move
    message(monster.name.capitalize() + ' is dead! You gained ' + str(monster.fighter.xp) + ' experience.', libtcod.dark_orange)
    monster.char = '%'
    monster.color = libtcod.dark_red
    monster.blocks = False
    monster.fighter = None
    monster.ai = None
    monster.name = 'remains of ' + monster.name
    monster.send_to_back()
    check_level_up()

def gateway_death(gateway):
    #turn the gateway into rubble
    message('The ' + gateway.name + 'is destroyed! You gained ' + str(gateway.fighter.xp) + ' experience.', libtcod.dark_orange)
    gateway.char = '%'
    gateway.color = libtcod.darkest_orange
    gateway.blocks = False
    gateway.fighter = None
    gateway.ai = None
    gateway.name = 'rubble'
    gateway.send_to_back()
    check_level_up()

def boss_death(boss):
    #turn the boss into a corpse
    message('You defeated the ' + boss.name + '! Your reward is ' + str(boss.fighter.xp) + ' experience!', libtcod.dark_orange)
    boss.char = '%'
    boss.blocks = False
    boss.fighter = None
    boss.ai = None
    boss.name = 'remnants of ' + boss.name
    boss.send_to_back()
    x = 0
    y = 0
    while True:
        x = libtcod.random_get_int(0, 0, MAP_WIDTH-1)
        y = libtcod.random_get_int(0, 0, MAP_HEIGHT-1)
        if not is_blocked(x, y):
            break
    ObjectFactory.create_object('late-stairs', x, y)
    check_level_up()

def target_tile(max_range = None):
    #return the position of a tile Left-clicked and in the player's FOV (optionally in a range),
    #or (None, None) if right clicked
    global key, mouse, fov_map
    while True:
        #render the screen. This erases the inventory and shows the names of objects under the mouse.
        libtcod.console_flush()
        libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS|libtcod.EVENT_MOUSE, key, mouse)
        render_all()

        (x, y) = (mouse.cx, mouse.cy)

        if (mouse.lbutton_pressed and libtcod.map_is_in_fov(fov_map, x, y) and (max_range is None or player.distance(x, y) <= max_range)):
            return (x, y)

        if mouse.rbutton_pressed or key.vk == libtcod.KEY_ESCAPE:
            return (None, None)  #cancel if the player right-clicked or pressed esc

def target_monster(max_range=None):
    #returns a clicked monster inside FOV up to a range, or None if right-clicked
    while True:
        (x, y) = target_tile(max_range)
        if x is None:  #player cancelled
            return None

        #return the first clicked monster, otherwise continue looping
        for obj in objects:
            if obj.x == x and obj.y == y and obj.fighter and obj != player:
                return obj

def closest_monster(max_range):
    #find closest enemy, up to a maximum range, and in the player's FOV
    closest_enemy = None
    closest_dist = max_range + 1  #start with (slightly more than) maximum range

    for object in objects:
        if object.fighter and not object == player and libtcod.map_is_in_fov(fov_map, object.x, object.y):
            dist = player.distance_to(object)
            if dist < closest_dist:  #it's closer, so remember it
                closest_enemy = object
                closest_dist = dist
    return closest_enemy

def cast_heal():
    global player
    #heal the player
    if player.fighter.hp == player.fighter.max_hp:
        message('You are already at full health.', libtcod.red)
        return 'cancelled'

    message('Your wounds start to feel better!', libtcod.light_violet)
    player.fighter.heal(HEAL_AMOUNT)

def cast_lightning():
    #find closest enemy (inside a maximum range) and damage it
    monster = closest_monster(LIGHTNING_RANGE)
    if monster is None:  #no enemy found within maximum range
        message('No enemy is close enough to strike.', libtcod.red)
        return 'cancelled'

    #zap it!
    message('You shot a bolt of lightning at the ' + monster.name + '! The damage is ' + str(LIGHTNING_DAMAGE) + ' hit points.', libtcod.light_blue)
    monster.fighter.take_damage(LIGHTNING_DAMAGE)

def cast_confuse():
    #ask the player for a target to confuse
    message('Left-click an enemy to confuse it, or right-click to cancel.', libtcod.lighter_yellow)
    monster = target_monster(CONFUSE_RANGE)
    if monster is None: return 'cancelled'

    #replace the monster's AI with a "confused" one; after some turns it will restore the old AI
    old_ai = monster.ai
    monster.ai = ConfusedMonster(old_ai)
    monster.ai.owner = monster  #tell the new component who owns it
    message('The ' + monster.name + ' was caught in the flashbang, and has become disoriented!', libtcod.lighter_yellow)

def cast_fireball():
    #Gotta lob them fireballs!
    #ask the player for a target tile to throw a fireball at
    message('Left-clock a target tile for the poison vial, or right-click to cancel.', libtcod.lighter_green)
    (x, y) = target_tile()
    if x is None: return 'cancelled'
    message('The noxious cloud rapidly expands ' + str(FIREBALL_RADIUS) + ' tiles from where you threw the vial.', libtcod.lighter_green)

    for obj in objects:  #damage every fighter in range, including the player
        if obj.distance(x, y) <= FIREBALL_RADIUS and obj.fighter:
            message('The ' + obj.name + ' is poisoned, dealing ' + str(FIREBALL_DAMAGE) + ' hit points.', libtcod.light_green)
            obj.fighter.take_damage(FIREBALL_DAMAGE)

def new_game():
    global player, objects, inventory, game_msgs, game_state, dungeon_level

    dungeon_level = 1

    objects = []

    #create objct representing the player
    ObjectFactory.create_object('player', SCREEN_WIDTH/2, SCREEN_HEIGHT/2)
    player.level = 1

    ### TEST BOSS CODE ###
    #player.fighter.base_max_hp = 4000
    #player.fighter.hp = 4000
    #player.fighter.base_power = 10
    #make_boss_map()
    ######################

    #generate map (at this point it's not drawn to the screen)
    make_map()
    initialize_fov()

    game_state = 'playing'
    inventory = []

    #create the list of game messages and their colours, starts empty
    game_msgs = []

    message('Welcome, Runner #43! Please refrain from spilling your blood on the walls!', libtcod.red)

def initialize_fov():
    global fov_recompute, fov_map
    fov_recompute = True

    libtcod.console_clear(con)

    #create the FOV map, according to the generated map
    fov_map = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            libtcod.map_set_properties(fov_map, x, y, not map[x][y].block_sight, not map[x][y].blocked)

def play_game():
    global key, mouse

    player_action = None

    mouse = libtcod.Mouse()
    key = libtcod.Key()
    while not libtcod.console_is_window_closed():
        #render the screen
        libtcod.sys_check_for_event(libtcod.EVENT_KEY_PRESS|libtcod.EVENT_MOUSE, key, mouse)
        render_all()
     
        libtcod.console_flush()
     
        #erase all objects at their old locations, before they move
        for object in objects:
            object.clear()
     
        #handle keys and exit game if needed
        player_action = handle_keys()
        if player_action == 'exit':
            save_game()
            break   

        #let monsters take their turn
        if game_state == 'playing' and player_action != 'didnt-take-turn':
            for object in objects:
                if object.ai:
                    object.ai.take_turn()

def next_level():
    global dungeon_level
    #advance to the next level
    message('Congratulations on passing test #' + str(dungeon_level) + '.', libtcod.light_violet)

    dungeon_level += 1
    message('On to the next trial, Runner #43!', libtcod.dark_violet)
    if dungeon_level != 10:
        make_map()
    else:
        make_boss_map()
    initialize_fov()

def main_menu():
    img = libtcod.image_load('main_background.png')
    

    while not libtcod.console_is_window_closed():
        #show the background image at twice the regular console resolution
        libtcod.image_blit_2x(img, 0, 0, 0)

        #show the game's title, and some credits!
        libtcod.console_set_default_foreground(0, libtcod.light_yellow)
        libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT/2 - 4, libtcod.BKGND_NONE, libtcod.CENTER, 'R U N N E R')
        libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT - 2, libtcod.BKGND_NONE, libtcod.CENTER, 'By Jake Uskoski')

        #show options and wait for the player's choice
        choice = menu('', ['Play a new game', 'Continue last game', 'Quit'], 24)

        if choice == 0:  #new game
            new_game()
            play_game()
        elif choice == 1:  #Load last game
            try:
                load_game()
            except:
                msgbox('\n No saved game to load.\n', 24)
                continue
            play_game()
        elif choice == 2:  #quit
            break

def save_game():
    file = shelve.open('savegame', 'n')
    file['map'] = map
    file['objects'] = objects
    file['player_index'] = objects.index(player)  #index of player in objects list
    file['inventory'] = inventory
    file['game_msgs'] = game_msgs
    file['game_state'] = game_state
    try:
        file['stairs_index'] = objects.index(stairs)
    except:
        file['stairs_index'] = -1
    file['dungeon_level'] = dungeon_level
    file.close()

def load_game():
    #open the previously saved shelve and load the game data
    global map, objects, player, inventory, game_msgs, game_state, stairs, dungeon_level

    file = shelve.open('savegame', 'r')
    map = file['map']
    objects = file['objects']
    player = objects[file['player_index']]  #get index of player in objects list and access it
    inventory = file['inventory']
    game_msgs = file['game_msgs']
    game_state = file['game_state']
    if file['stairs_index'] != -1:
        stairs = objects[file['stairs_index']]
    dungeon_level = file['dungeon_level']
    file.close()

    initialize_fov()


#############################################
# Initialization & Main Loop
#############################################

libtcod.console_set_custom_font('arial10x10.png', libtcod.FONT_TYPE_GREYSCALE | libtcod.FONT_LAYOUT_TCOD)
libtcod.console_init_root(SCREEN_WIDTH, SCREEN_HEIGHT, 'R U N N E R', False)
libtcod.sys_set_fps(LIMIT_FPS)
con = libtcod.console_new(SCREEN_WIDTH, SCREEN_HEIGHT)
panel = libtcod.console_new(SCREEN_WIDTH, PANEL_HEIGHT)


main_menu()
