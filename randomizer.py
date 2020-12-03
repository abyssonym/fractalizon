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
from sys import argv, exc_info
from traceback import print_exc


VERSION = 1
DIFFICULTY_FACTORS = [2, 1, 0.61, 0.4]
MAX_SHOP_INVENTORY = 32

nameslibrary = defaultdict(dict)
for nametype in ['pin', 'threads', 'food', 'swag', 'enemy']:
    filename = '%s_names.txt' % nametype
    with open(path.join(tblpath, filename)) as f:
        for line in f:
            line = line.strip()
            index, name = line.split(' ', 1)
            index = int(index, 0x10)
            nameslibrary[nametype][index] = name


class VanillaObject(TableObject):
    flag = 'v'
    flag_description = 'nothing'


class EnemyObject(TableObject):
    flag = 'd'
    flag_description = 'enemy drops'
    custom_random_enable = 'd'

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

    def cleanup(self):
        if 'lowlevel' in get_activated_codes():
            self.exp = 0

        if 'easymodo' in get_activated_codes():
            self.hp = 1
            self.attack = 1

        if 'extra' in get_activated_codes():
            self.drop_rates = [10000] * 4


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

    @classmethod
    def get_by_index(cls, index):
        item = (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[index]
        return item

    @classmethod
    def get_index_by_item(cls, item):
        index = (PinObject.every + ThreadsObject.every +
                 FoodObject.every + SwagObject.every).index(item)
        return index

    def price_cleanup(self):
        if 'phantomthief' in get_activated_codes():
            self.price = 0

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
        self.price = price // 2
        if self.price % 10:
            self.price += 10 - (self.price % 10)

    def preclean(self):
        self.price_cleanup()


class PinObject(ItemObject):
    namekey = 'pin'

    randomselect_attributes = ['brand']

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

    def cleanup(self):
        if self in self.yen_pins or ShopItemObject.flag not in get_flags():
            self.brand = self.old_data['brand']


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

    @classproperty
    def randomselect_attributes(self):
        randomselect_attributes = []
        if AbilityObject.flag in get_flags():
            randomselect_attributes.append('ability')

        if ShopItemObject.flag in get_flags():
            randomselect_attributes.append('brand')

        return randomselect_attributes

    def cleanup(self):
        if 'fierce' in get_activated_codes():
            self.bravery = 1

        for attr in self.mutate_attributes:
            if self.old_data[attr] == 0:
                setattr(self, attr, 0)


class FoodObject(ItemObject):
    flag = 'f'
    flag_description = 'food'
    custom_random_enable = 'f'
    namekey = 'food'

    mutate_attributes = {
        'bites': None,
        'price': None,
        'boost': None,
        'sync': None,
        }

    def cleanup(self):
        if 'vegan' in get_activated_codes() and self.status < 3:
            self.boost = 0

        if 'foodie' in get_activated_codes():
            self.bites = 1

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
    def __repr__(self):
        s = '{0:0>4X} {1:0>4X} {2} {3}'.format(
            self.quest_index, self.item_index, self.item, self.unknown)
        for m, a in zip(self.materials, self.amounts):
            if a == 0:
                continue
            item = (PinObject.every + ThreadsObject.every +
                    FoodObject.every + SwagObject.every)[m]
            s += '\n    {0}x {1}'.format(a, item.name)
        return s

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

    @property
    def brand(self):
        if hasattr(self.item, 'brand'):
            return self.item.brand

    @cached_property
    def rank(self):
        return self.old_item.rank

    @cached_property
    def price(self):
        return self.item.old_data['price']

    @property
    def name(self):
        return self.item.name


class ShopCastObject(TableObject): pass


class ShopItemObject(TableObject):
    flag = 'b'
    flag_description = 'shop stocks and brands'
    custom_random_enable = 'b'

    randomselect_attributes = ['day_available']

    @classproperty
    def after_order(cls):
        return [PinObject, ThreadsObject]

    def __repr__(self):
        return '{0:0>2X}-{1:0>3X} {2:0>4X} {3:0>2} {4:0>2} {5}'.format(
            self.shop_index, self.index, self.item_index,
            self.item.brand
            if hasattr(self.item, 'brand') and self.item.brand is not None
            else 'XX',
            self.day_available, self.item.name)

    @cached_property
    def old_item(self):
        item_index = self.old_data['item_index']
        if item_index >= 0x320:
            return QuestObject.get_by_quest_index(item_index)

        return (PinObject.every + ThreadsObject.every +
                FoodObject.every + SwagObject.every)[item_index]

    @property
    def item(self):
        if (hasattr(self, '_previous_item_index')
                and self.item_index == self._previous_item_index):
            return self._previous_item

        if self.item_index >= 0x320:
            item = QuestObject.get_by_quest_index(self.item_index)
        else:
            item = (PinObject.every + ThreadsObject.every +
                    FoodObject.every + SwagObject.every)[self.item_index]

        self._previous_item_index = self.item_index
        self._previous_item = item
        return self.item

    def get_brand(self, old=False):
        if old:
            item = self.old_item
        else:
            item = self.item

        if isinstance(item, QuestObject):
            if old:
                item = item.old_item
            else:
                item = item.item

        if hasattr(item, 'brand'):
            if old:
                return item.old_data['brand']
            else:
                return item.brand
        return None

    @cached_property
    def rank(self):
        return self.old_item.rank

    @classmethod
    def get_items_by_shop_index(cls, index, old=False):
        if old:
            return [si for si in ShopItemObject.every
                    if si.old_data['shop_index'] == index]
        return [si for si in ShopItemObject.every if si.shop_index == index]

    @classmethod
    def get_shop_brands(cls, index):
        if index in ShopItemObject.restaurants:
            return set([])

        items = ShopItemObject.get_items_by_shop_index(index, old=True)
        brands = Counter([i.get_brand(old=True) for i in items
                          if i.get_brand(old=True) is not None])
        if not brands:
            return set([])

        maxbrand = brands[max(brands, key=lambda b: brands[b])]
        brands = set([b for b in brands if brands[b] >= (maxbrand/2) >= 1])
        return brands

    @classmethod
    def get_primary_brand(cls, index):
        if index in ShopItemObject.restaurants:
            return set([])

        items = ShopItemObject.get_items_by_shop_index(index, old=True)
        brands = Counter([i.get_brand(old=True) for i in items
                          if i.get_brand(old=True) is not None])
        brands = [b for b in brands if brands[b] >= len(items)/2]
        if len(brands) == 1:
            return brands[0]
        return None

    @classproperty
    def shop_indexes(cls):
        if hasattr(ShopItemObject, '_shop_indexes'):
            return ShopItemObject._shop_indexes

        indexes = set([si.old_data['shop_index']
                       for si in ShopItemObject.every])
        ShopItemObject._shop_indexes = indexes
        return ShopItemObject.shop_indexes

    @classproperty
    def restaurants(cls):
        if hasattr(ShopItemObject, '_restaurants'):
            return ShopItemObject._restaurants

        restaurants = set([])
        for sindex in ShopItemObject.shop_indexes:
            items = ShopItemObject.get_items_by_shop_index(sindex, old=True)
            foods = [i for i in items if isinstance(i, FoodObject)
                     or (isinstance(i, QuestObject)
                         and isinstance(i.item, FoodObject))]
            if len(foods) >= len(items)/2:
                restaurants.add(sindex)

        ShopItemObject._restaurants = restaurants
        return ShopItemObject.restaurants

    @classmethod
    def randomize_brands(cls):
        for o in ThreadsObject.every + PinObject.every:
            if o in PinObject.yen_pins:
                continue
            o.reseed('brand')
            o.brand = o.get_similar(
                random_degree=ShopItemObject.random_degree).old_data['brand']

    def randomize(self):
        super(ShopItemObject, self).randomize()
        if isinstance(self.item, PinObject):
            candidates = [p for p in PinObject.every
                          if p not in PinObject.yen_pins]
            assert self.item in candidates
            new_item = self.item.get_similar(
                candidates, random_degree=ShopItemObject.random_degree)
            self.item_index = ItemObject.get_index_by_item(new_item)
            assert self.item == new_item

    @classmethod
    def randomize_all(cls):
        super(ShopItemObject, cls).randomize_all()

        ShopItemObject.class_reseed('brands')
        ShopItemObject.randomize_brands()

        ShopItemObject.class_reseed('shops')
        to_assign = list(ShopItemObject.every)
        random.shuffle(to_assign)

        shops = defaultdict(list)
        for sio in to_assign:
            sio.reseed('shop')

            candidates = [
                c for c in ShopItemObject.every
                if len(shops[c.old_data['shop_index']]) <= MAX_SHOP_INVENTORY]

            if sio.get_brand() is None:
                temp = [s2 for s2 in candidates
                        if s2.get_brand() is None
                        and type(sio.item) is type(s2.old_item)]
            else:
                temp = [
                    s2 for s2 in candidates
                    if s2.get_brand(old=True) is not None
                    and s2.get_brand(old=True) == sio.get_brand()]

            candidates = temp if temp else candidates

            if shops:
                temp = [c for c in candidates
                        if sio.item not in shops[c.old_data['shop_index']]]
                candidates = temp if temp else candidates

                max_shop = max(shops, key=lambda s: len(shops[s]))
                max_shop_size = len(shops[max_shop])
                if max_shop_size > 0:
                    max_shops = [s for s in shops
                                 if len(shops[s]) >= max_shop_size]
                    temp = [c for c in candidates
                            if c.old_data['shop_index'] not in max_shops]
                    candidates = temp if temp else candidates

            chosen = random.choice(candidates)
            sio.shop_index = chosen.old_data['shop_index']
            shops[sio.shop_index].append(sio.item)
            assert len(shops[sio.shop_index]) <= MAX_SHOP_INVENTORY

    @classmethod
    def full_preclean(cls):
        SHOPS_FILENAME = path.join(tblpath, 'accessible_shops.txt')
        area_shops = {}
        for line in open(SHOPS_FILENAME):
            line = line.strip()
            if not (line and line[0] != '#'):
                continue
            area, shops = line.split(':')
            shops = {int(s, 0x10) for s in shops.split(',')}
            area_shops[area] = shops

        AREAS_FILENAME = path.join(tblpath, 'accessible_areas.txt')
        day_shops = defaultdict(set)
        for line in open(AREAS_FILENAME):
            line = line.strip()
            if not (line and line[0] != '#'):
                continue
            weekday, areas = line.split(':')
            week, day = weekday.split('-')
            week, day = int(week), int(day)
            day = ((week-1) * 7) + day
            areas = areas.split(',')
            for area in areas:
                day_shops[day] |= area_shops[area]

        def ensure_item_access(index, day):
            item = ItemObject.get_by_index(index)
            ensure_shops = sorted(day_shops[day])

            existing_this = [sio for sio in ShopItemObject.every
                             if sio.item is item
                             and not hasattr(sio, '_is_protected')]
            if existing_this:
                chosen = random.choice(existing_this)
            else:
                shuffled_shop_items = sorted(
                    ShopItemObject.every,
                    key=lambda sio: (not hasattr(sio, '_is_protected'),
                                     sio.signature))
                seen_items = set([])
                chosen = None
                for sio in shuffled_shop_items:
                    if (sio.item in seen_items
                            and not hasattr(sio, '_is_protected')):
                        chosen = sio
                        break
                    seen_items.add(sio.item)
                chosen.shop_index = None

            chosen.day_available = min(day, chosen.day_available)
            chosen.item_index = index
            assert not hasattr(chosen, '_is_protected')
            chosen._is_protected = True
            if chosen.shop_index in ensure_shops:
                return True

            ensure_shops = sorted(ensure_shops)
            temp = [s for s in ensure_shops
                    if len(ShopItemObject.get_items_by_shop_index(s))
                    < MAX_SHOP_INVENTORY]
            if temp:
                ensure_shops = temp

            if hasattr(item, 'brand') and item.brand <= 12:
                temp = [s for s in ensure_shops
                        if ShopItemObject.get_primary_brand(s) == item.brand]
                if temp:
                    ensure_shops = temp

            chosen.shop_index = random.choice(ensure_shops)

        REQS_FILENAME = path.join(tblpath, 'requirements.txt')
        for line in open(REQS_FILENAME):
            line = line.strip()
            if not (line and line[0] != '#'):
                continue
            weekday, reqs = line.split(':')
            week, day = weekday.split('-')
            week, day = int(week), int(day)
            day = ((week-1) * 7) + day
            reqs = reqs.split(',')
            for req in reqs:
                if req.startswith('$'):
                    brand = int(req[1:], 0x10)
                    used_equip_types = {3}  # ignore top & bottom from start
                    four_lowest = set([])
                    while len(four_lowest) < 4:
                        candidates = sorted(
                            [t for t in ThreadsObject.every
                             if t.equip_type not in used_equip_types
                             and t.brand == brand],
                            key=lambda tt: (tt.bravery, tt.signature))
                        if not candidates:
                            raise Exception("Impossible seed.")
                        chosen = candidates[0]
                        four_lowest.add(chosen)
                        used_equip_types.add(chosen.equip_type)
                    for t in sorted(four_lowest):
                        index = ItemObject.get_index_by_item(t)
                        ensure_item_access(index, day)
                else:
                    index = int(req, 0x10)
                    ensure_item_access(index, day)

        #import pdb; pdb.set_trace()
        super(ShopItemObject, cls).full_preclean()

    @classmethod
    def full_cleanup(cls):
        for sio in ShopItemObject.every:
            similars = [s for s in ShopItemObject.every if s.item == sio.item]
            assert sio in similars
            day_available = min([s.day_available for s in similars])
            for s in similars:
                s.day_available = day_available

        sorted_shop_items = sorted(
            ShopItemObject.every,
            key=lambda o: (
                o.shop_index, hasattr(o.item, 'price'),
                not isinstance(o.item, QuestObject),
                -o.item.price if hasattr(o.item, 'price') else None,
                o.item_index))
        sorted_shop_items = [
            (o.shop_index, o.item_index, o.item_type_code, o.day_available)
            for o in sorted_shop_items]

        assert len(sorted_shop_items) == len(ShopItemObject.every)
        for sio, (shop_index, item_index, item_type_code, day_available) in \
                zip(ShopItemObject.every, sorted_shop_items):
            sio.shop_index = shop_index
            sio.item_index = item_index
            sio.item_type_code = item_type_code
            sio.day_available = day_available
            del(sio._property_cache['old_item'])

        super(ShopItemObject, cls).full_cleanup()

    def cleanup(self):
        if self.item.price == 0 and 'Rare Metal' in self.item.name:
            self.item.price = 1000
        if self.item.price == 0 and not isinstance(self.item, QuestObject):
            print('WARNING: 0 yen item -', self)


if __name__ == '__main__':
    try:
        print('TWEWY "Fractalizon" randomizer v%s' % VERSION)
        print('{0}'.format('-' * 79))

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {'easymodo': ['easymodo'],
                 'extra': ['extra'],
                 'phantomthief': ['phantomthief'],
                 'fierce': ['fierce'],
                 'foodie': ['foodie'],

                 'vegan': ['vegan'],
                 'lowlevel': ['lowlevel', 'llg'],
                }

        run_interface(ALL_OBJECTS, snes=False, codes=codes,
                      custom_degree=True)

        clean_and_write(ALL_OBJECTS)
        finish_interface()

    except Exception:
        print_exc()
        print('ERROR:', exc_info()[1])
        input('Press Enter to close this program. ')
