from randomtools.utils import read_multi
from sys import argv
from subprocess import call

FILENAME_ADDR = 0x3ac090
FILEPTR_ADDR = 0x3afe00

f = open(argv[1])
f.seek(FILENAME_ADDR)

filenames = []
sub_filenames = []
seen_null = False
while True:
    is_folder = False
    length = ord(f.read(1))
    if length == 0x00:
        filenames.append(sub_filenames)
        sub_filenames = []
        seen_null = True
        continue
    if length == 0xFF:
        break
    if length & 0x80:
        is_folder = True
        seen_null = False
        length = (length & 0x7F)+1
    else:
        assert seen_null or True
    filename = f.read(length)
    if is_folder:
        filename = '+' + filename
        filenames.append(filename)
    else:
        sub_filenames.append(filename)
    if is_folder:
        peek = ord(f.read(1))
        assert peek == 0xF0

filenames.append(sub_filenames)

f.seek(FILEPTR_ADDR)

addresses = []
while True:
    start_addr = read_multi(f, length=4)
    end_addr = read_multi(f, length=4)
    if 0xFFFFFFFF in [start_addr, end_addr]:
        break
    addresses.append((start_addr, end_addr))

f.close()

old_filenames = list(filenames)
foldernames = [fs for fs in filenames if isinstance(fs, basestring)]
filenames = [fs for fs in filenames if fs and not isinstance(fs, basestring)]

foldernames = sorted(foldernames, key=lambda f: f[-1])
folderdict = {}

addresses = addresses[48:]
temp = [f for fs in filenames for f in fs]
assert len(addresses) == len(temp)

for (i, fs) in enumerate(filenames):
    name = 'FOLDER'
    mystery = i

    new_foldername = "{0}_{1:0>2X}".format(name, mystery)
    new_foldername = "{0}_{1:0>2X}".format('FOLDER', mystery)
    folderdict[new_foldername] = fs
    call(['mkdir', '-p', 'dump/%s' % new_foldername])
    print "+%s" % new_foldername
    for fn in fs:
        fnn = 'dump/%s/%s' % (new_foldername, fn)
        f = open(fnn, 'w+')
        f.close()

        start, finish = addresses.pop(0)
        length = finish-start
        print "{0:0>7X} {1: <6X} : {2}".format(start, length, fn)

        g = open(argv[1])
        g.seek(start)
        data = g.read(length)
        g.close()
        f = open(fnn, 'r+b')
        f.write(data)
        f.close()
    print
