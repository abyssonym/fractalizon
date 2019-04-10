from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses, get_random_degree,
    get_activated_patches, mutate_normal, shuffle_normal, gen_random_normal,
    write_patch)
from randomtools.utils import (
    classproperty, cached_property, get_snes_palette_transformer,
    read_multi, write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes, activate_code,
    run_interface, rewrite_snes_meta, clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter, ItemRouterException
from collections import defaultdict
from os import path
from time import time, sleep, gmtime
from collections import Counter
from itertools import combinations
from sys import argv


VERSION = 1
DIFFICULTY_FACTORS = [2, 1, 0.61, 0.4]

nameslibrary = defaultdict(dict)
for nametype in ['pin', 'threads', 'food', 'swag', 'enemy']:
    filename = '%s_names.txt' % nametype
    with open(path.join(tblpath, filename)) as f:
        for line in f:
            line = line.strip()
            index, name = line.split(' ', 1)
            index = int(index, 0x10)
            nameslibrary[nametype][index] = name


class EnemyObject(TableObject):
    flag = 'd'
    flag_description = 'enemy drops'
    custom_random_enable = True

    mutate_attributes = {
            'drop_rates': None,
        }

    def __repr__(self):
        return '{0:0>2X} {2:>5} {3:>4} {1} :: {4}'.format(
            self.index, self.name, self.hp, self.attack,
            ';'.join(self.drop_names))

    @cached_property
    def intershuffle_valid(self):
        return '???' not in self.name and set(self.drops) != {0}

    @cached_property
    def rank(self):
        return self.old_data['hp']

    @property
    def name(self):
        return nameslibrary['enemy'][self.index]

    @cached_property
    def fixed_drop_indexes(self):
        return [d if d < 1000 else d-1000 for d in self.drops]

    @cached_property
    def old_drop_names(self):
        names = []
        for d in self.fixed_drop_indexes:
            names.append(nameslibrary['pin'][d])
        return names

    @property
    def drop_names(self):
        names = []
        for d in self.drops:
            names.append(nameslibrary['pin'][d % 1000])
        return names

    @cached_property
    def old_drops_pins(self):
        return [PinObject.get(d) for d in self.fixed_drop_indexes]

    def mutate_drops(self):
        new_drops = []
        for (i, d) in enumerate(self.old_drops_pins):
            other = self.get_similar().old_drops_pins[i]
            if other in PinObject.yen_pins:
                new = d.get_similar(PinObject.yen_pins, override_outsider=True)
            else:
                new = d.get_similar()
            new_drops.append(new.index)
        self.drops = new_drops

    def mutate(self):
        super(EnemyObject, self).mutate()
        self.mutate_drops()


class ItemObject(TableObject):
    @property
    def name(self):
        try:
            return nameslibrary[self.namekey][self.index]
        except KeyError:
            return 'Unknown {0} {1:0>3X}'.format(
                self.__class__.__name__, self.index)

    @cached_property
    def is_buyable(self):
        for si in ShopItemObject.every:
            if si.old_item is self:
                return True
        return False

    @cached_property
    def is_quest_buyable(self):
        if self.is_buyable:
            return True
        for si in ShopItemObject.every:
            if (isinstance(si.old_item, QuestObject)
                    and si.old_item.old_item is self):
                return True
        return False

    @cached_property
    def old_shop_availability(self):
        days = [si.old_data['day_available'] for si in ShopItemObject.every
                if si.old_item is self
                or (isinstance(si.old_item, QuestObject)
                    and si.old_item.old_item is self)]
        days = [d for d in days if d]
        if days:
            return min(days)
        return 100

    @cached_property
    def intershuffle_valid(self):
        if not self.old_data['price']:
            return False
        if self.name.startswith('(') or self.name.startswith('Unknown'):
            return False
        return True

    @property
    def rank(self):
        if not self.intershuffle_valid:
            return -1

        if hasattr(self, '_rank'):
            return self._rank

        sorted_items = sorted(
            self.every, key=lambda o: (o.old_data['price'], o.signature))
        sorted_items = [o for o in sorted_items if o.intershuffle_valid]
        for o in sorted_items:
            o._rank = sorted_items.index(o) / float(len(sorted_items)-1)

        return self.rank

    def price_cleanup(self):
        if self.price == self.old_data['price']:
            return

        price = self.price * 2
        counter = 0
        while price >= 100:
            price = int(round(price / 10.0))
            counter += 1
            if random.randint(1, 10) == 10:
                break
        price = price * (10**counter)
        self.price = price / 2
        if self.price % 10:
            self.price += 10 - (self.price % 10)

    def preclean(self):
        self.price_cleanup()


class PinObject(ItemObject):
    namekey = 'pin'

    @property
    def intershuffle_valid(self):
        return True

    @classproperty
    def yen_pins(cls):
        if hasattr(PinObject, '_yen_pins'):
            return PinObject._yen_pins

        #yen_pins = [p for p in PinObject.every if p.name.endswith(' Yen')]
        yen_pins = [p for p in PinObject.every if 245 <= p.index <= 260]

        PinObject._yen_pins = yen_pins
        return PinObject.yen_pins

    @cached_property
    def drop_rank(self):
        ranks = []
        for e in EnemyObject.every:
            if not e.intershuffle_valid:
                continue
            for difficulty, drop, drop_rate in zip(
                    DIFFICULTY_FACTORS, e.fixed_drop_indexes, e.drop_rates):
                if drop == self.index:
                    assert self.name in e.old_drop_names
                    rank = drop_rate * e.rank / (difficulty * 10000.0)
                    rank = e.rank / difficulty
                    if rank > 0:
                        ranks.append(rank)
        if ranks:
            return sum(ranks) / float(len(ranks))
        return 0

    @property
    def rank(self):
        if hasattr(self, '_rank'):
            return self._rank

        by_price = sorted(self.every, key=lambda p: (p.price, p.signature))
        by_price = [p for p in by_price if p.price > 0 and p.is_buyable]
        by_drop_rank = sorted(
            self.every, key=lambda p: (p.drop_rank, p.signature))
        by_drop_rank = [p for p in by_drop_rank if p.drop_rank > 0]
        by_shop_day = sorted(
            self.every, key=lambda p: (p.old_shop_availability, p.signature))
        by_shop_day = [p for p in by_shop_day if p.is_quest_buyable]

        for p in self.every:
            ranks = []
            if p in by_price and p.is_buyable:
                ranks.append(by_price.index(p) / float(len(by_price))-1)
            if p in by_drop_rank:
                ranks.append(
                    by_drop_rank.index(p) / float(len(by_drop_rank))-1)
            if ranks:
                p._rank = min(ranks)

        for p in self.every:
            if hasattr(p, '_rank'):
                for ev in p.evolves:
                    if ev:
                        p2 = PinObject.get(ev)
                        if not hasattr(p2, '_rank') or p2._rank < p._rank:
                            value = gen_random_normal() ** 4
                            new_rank = (value * 1.0) + ((1-value) * p._rank)
                            p2._rank = new_rank

        by_price = sorted(self.every, key=lambda p: (p.price, p.signature))
        by_price = [p for p in by_price if p.price > 0]
        for p in self.every:
            if hasattr(p, '_rank'):
                continue

            if p in by_shop_day:
                p._rank = by_shop_day.index(p) / float(len(by_shop_day)-1)
            elif p in by_price:
                p._rank = by_price.index(p) / float(len(by_price)-1)
            else:
                p._rank = random.random()

        sorted_class = sorted(
            self.every, key=lambda p: (-p.pin_class, p._rank, p.signature))
        sorted_noclass = sorted(
            self.every, key=lambda p: (p._rank, p.signature))
        for p in self.every:
            if p.pin_class >= 5:
                rank = sorted_noclass.index(p)
            else:
                value = gen_random_normal()
                rank = ((sorted_class.index(p) * value)
                        + ((1-value) * sorted_noclass.index(p)))
            p._rank = mutate_normal(
                rank, minimum=0, maximum=len(self.every), wide=True,
                random_degree=self.random_degree**2, return_float=True)

        sorted_noclass = sorted(
            self.every, key=lambda p: (p._rank, p.signature))
        for p in self.every:
            p._rank = sorted_noclass.index(p) / float(len(sorted_noclass)-1)

        return self.rank


class AbilityObject(TableObject):
    flag = 'a'
    flag_description = 'threads abilities'
    custom_random_enable = 't'


class ThreadsObject(ItemObject):
    flag = 't'
    flag_description = 'threads stats'
    custom_random_enable = 't'
    namekey = 'threads'

    mutate_attributes = {
        'price': None,
        'bravery': None,
        'defense': None,
        'attack': None,
        'hp': None,
        }
    randomselect_attributes = ['ability']

    def cleanup(self):
        for attr in self.mutate_attributes:
            if self.old_data[attr] == 0:
                setattr(self, attr, 0)

        if AbilityObject.flag not in get_flags():
            self.ability = self.old_data['ability']


class FoodObject(ItemObject):
    flag = 'f'
    flag_description = 'food'
    custom_random_enable = True
    namekey = 'food'

    mutate_attributes = {
        'bites': None,
        'price': None,
        'boost': None,
        'sync': None,
        }

    def cleanup(self):
        if self.sync == self.old_data['sync']:
            return
        self.sync = int(round(self.sync * 2 / 10.0)) * 5


class SwagObject(ItemObject):
    flag = 't'
    custom_random_enable = 't'
    namekey = 'swag'
    mutate_attributes = {
        'price': None,
        }


class QuestObject(TableObject):
    @classmethod
    def get_by_quest_index(cls, quest_index):
        candidates = [q for q in QuestObject.every
                      if quest_index == q.quest_index]
        assert len(candidates) == 1
        return candidates[0]

    @cached_property
    def old_item(self):
        item_index = self.old_data['item_index']
        return (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[item_index]

    @property
    def item(self):
        return (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[self.item_index]

    @cached_property
    def rank(self):
        return self.old_item.rank

    @cached_property
    def price(self):
        return self.item.old_data['price']

    @property
    def name(self):
        return self.item.name


class ShopItemObject(TableObject):
    def __repr__(self):
        return '{0:0>2X}-{1:0>3X} {2:0>4X} {3:0>2} {4}'.format(
            self.shop_index, self.index, self.item_index,
            self.day_available, self.item.name)

    @cached_property
    def old_item(self):
        item_index = self.old_data['item_index']
        if self.item_index >= 0x320:
            return QuestObject.get_by_quest_index(item_index)

        return (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[item_index]

    @property
    def item(self):
        if self.item_index >= 0x320:
            return QuestObject.get_by_quest_index(self.item_index)

        return (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[self.item_index]

    @cached_property
    def rank(self):
        return self.old_item.rank


if __name__ == '__main__':
    try:
        print ('TWEWY randomizer v%s' % VERSION)
        print '-' * 79
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {'easymodo': ['easymodo'],
                }

        run_interface(ALL_OBJECTS, snes=False, codes=codes,
                      custom_degree=True)

        clean_and_write(ALL_OBJECTS)

        finish_interface()

    except Exception, e:
        print 'ERROR: %s' % e
        raw_input('Press Enter to close this program. ')
