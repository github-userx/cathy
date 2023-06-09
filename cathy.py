#!python3
'''
attempt to build a python class to read cathy's .caf file (by Jerome)
2017/05/31  got entrydat.cpp from Robert Vasicek rvas01@gmx.net :)
2017/06/02  first reading/struct. conversion from entrydat.cpp
2017/06/03  first complete read of a .caf
            first query functions

cat.pathcat		# catalogfilename in the cathy's ui
cat.date
cat.device
cat.volume 		# name in 'volume' column
cat.alias   	# name in first Cathy column
cat.volumename
cat.serial
cat.comment
cat.freesize
cat.archive

cat.elm will contain every element (folder name ot filename)
cat.elm[69] returns a tuple with (date, size, parent folder id, filename) and if it is a dir with (date, -dir_id, parent folder id, filename)
				where dir_id matches the cat.info index, so negative size indicates a dir.
cat.info[folder id] returns a tuple (id, filecount, dirsize)
	original Cathy does not include the id, but for internal python representation this is easier (to perform sort of info array)

# Vincent continues with Jerome's code
2021/03/09	All unpack formats fixed for endianness so the Python code will run on mac and linux systems
2021/03/10	removed some modifications to the original code that I didn't worked correctly (at least not for me):
			- 2 to 4 byte change in m_sPathName
			- [2:-1] truncation in catpath
			Added search functions
2021/03/11	Refactored the code to allow empty constructor and classmethods so it will be possible to write scan function in python
			- CathyCat.from_file(path)
2021/03/12	Added new functionality
			- write function that can write a .caf file from a previously read file
			- scan function that can create a .caf file, works for linux and osx. Windows not yet, but original Cathy (or CathyCmd) already works for windows.
2021/03/13	Some more fixes
			- tree wouldn't render right in the original Cathy; this was some trial and error and mainly caused by the order of the items in the list
			- free space corrected for different platforms
			- wrestled with Unicode / Ascii / str / byte troubles
			- added some hacks so the code will run with python 2 as well as 3
			- added command line arguments implementation for the search and scan functions
2021/03/25  Some functions changed and some new functions to implement a directory browsing option
			- get_children() and lookup_dir_id(). One would expect the original lookup() function to work, but I'm not sure what this does.
2022/03/10  Added support for m_sVersion 8 by changing the m_sPathName to '<L' (was 'H' in version 7 and older)
            This is what was probably removed at 21/03/10, but that implemenation lacked backward compatibility..
2022/03/11  Added support for v8 filesave, but still defaults to v7
2022/08/05  Fixed support for foreign characters (see github issue)
2022/08/28  Fixed a bug (saveVersion -> self.saveVersion)
2022/09/14  Replaced the readstring function by a new version that should work better with UTF-8!?

USAGE

# to search for something in all .caf files in the cwd
python cathy.py search <searchitem>
# to create a .caf file with the same name as the volume in cwd
python cathy.py scan <path>
# the same as scan but with Cathy archive set
python cathy.py scanarchive <path>
# display disk usage overview
python cathy.py usage
'''

from __future__ import (print_function, division)
__metaclass__ = type

import time
import datetime
import subprocess
import os
from os import path as ospath
from struct import calcsize, unpack, pack
from time import ctime
from binascii import b2a_hex
import shutil

from sys import platform, version_info, argv

DEBUG = False


class CathyCat():

    ulCurrentMagic = 3500410407
    ulMagicBase = 500410407
    # ulMagicBase =     251327015
    ulModus = 1000000000
    #saveVersion = 7
    saveVersion = 8
    sVersion = 8  # got a 7 in the .cpp file you share with me, but got an 8 in my .cat testfile genrated in cathy v2.31.3

    delim = b'\x00'

    def __init__(self, pathcatname, m_timeDate, m_strDevice, m_strVolume, m_strAlias, m_szVolumeName, m_dwSerialNumber, m_strComment, m_fFreeSize, m_sArchive, info, elm):
        '''
        read a cathy .caf file
        and import it into a python instance
        '''
        self.pathcat = pathcatname		# catalogfilename in the cathy's ui
        self.date = m_timeDate
        self.device = m_strDevice
        self.volume = m_strVolume
        self.alias = m_strAlias
        self.volumename = m_szVolumeName
        self.serial = m_dwSerialNumber
        self.comment = m_strComment
        self.freesize = m_fFreeSize
        self.archive = m_sArchive
        self.totaldirs = 0

        self.info = info
        self.elm = elm

    @classmethod
    def from_file(cls, pathcatname, no_elm=False):

        try:
            cls.buffer = open(pathcatname, 'rb')
        except:
            return

        # m_sVersion - Check the magic
        ul = cls.readbuf('<L')  # 4 bytes
        if ul > 0 and ul % CathyCat.ulModus == CathyCat.ulMagicBase:
            m_sVersion = int(ul/CathyCat.ulModus)
        else:
            cls.buffer.close()
            print("Incorrect magic number for caf file",
                  pathcatname, "(", ul % CathyCat.ulModus, ")")
            return

        if m_sVersion > 2:
            m_sVersion = cls.readbuf('h')  # 2 bytes

        if m_sVersion > CathyCat.sVersion:
            print("Incompatible caf version for", pathcatname, "(", m_sVersion, ")")
            return
        #print(f"Version: {m_sVersion}")

        # m_timeDate
        m_timeDate = ctime(cls.readbuf('<L'))  # 4 bytes

        # m_strDevice - Starting version 2 the device is saved
        if m_sVersion >= 2:
            m_strDevice = cls.readstring()

        # m_strVolume, m_strAlias > m_szVolumeName
        m_strVolume = cls.readstring()
        m_strAlias = cls.readstring()
        if DEBUG:
            print(m_strVolume, m_strAlias)

        if len(m_strAlias) == 0:
            m_szVolumeName = m_strVolume
        else:
            m_szVolumeName = m_strAlias

        # m_dwSerialNumber well, odd..
        bytesn = cls.buffer.read(4)  # 4 bytes
        rawsn = b2a_hex(bytesn).decode().upper()
        sn = ''
        while rawsn:
            chunk = rawsn[-2:]
            rawsn = rawsn[:-2]
            sn += chunk
        m_dwSerialNumber = '%s-%s' % (sn[:4], sn[4:])

        # m_strComment
        if m_sVersion >= 4:
            m_strComment = cls.readstring()

        # m_fFreeSize - Starting version 1 the free size was saved
        if m_sVersion >= 1:
            m_fFreeSize = cls.readbuf('<f')  # as megabytes (4 bytes)
        else:
            m_fFreeSize = -1  # unknow

        # m_sArchive
        if m_sVersion >= 6:
            m_sArchive = cls.readbuf('h')  # 2 bytes
            if m_sArchive == -1:
                m_sArchive = 0

        # folder information : file count, total size
        m_paPaths = []
        lLen = cls.readbuf('<l')  # 4 bytes
        if DEBUG:
            print("#Folders:", lLen)
        tcnt = 0
        for l in range(lLen):
            if l == 0 or m_sVersion <= 3:
                m_pszName = cls.readstring()
            if m_sVersion >= 3:
                m_lFiles = cls.readbuf('<l')  # 4 bytes
                m_dTotalSize = cls.readbuf('<d')  # 8 bytes
            if DEBUG:
                print(tcnt, m_lFiles, m_dTotalSize)
            m_paPaths.append((tcnt, m_lFiles, m_dTotalSize))
            tcnt = tcnt + 1

        info = m_paPaths

        if no_elm:
            cls.buffer.close()
            return cls(pathcatname, m_timeDate, m_strDevice, m_strVolume, m_strAlias, m_szVolumeName, m_dwSerialNumber, m_strComment, m_fFreeSize, m_sArchive, info, [])

        # files : date, size, parentfolderid, filename
        # if it's a folder :  date, -thisfolderid, parentfolderid, filename
        m_paFileList = []
        lLen = cls.readbuf('<l')  # 4 bytes
        if DEBUG:
            print("#Files:", lLen)
        for l in range(lLen):
            # elmdate = ctime(cls.readbuf('<L'))
            elmdate = cls.readbuf('<L')  # 4 bytes
            if m_sVersion <= 6:
                # later, won't test for now
                m_lLength = 0
            else:
                # m_lLength = cls.buffer.read(8)
                m_lLength = cls.readbuf('<q')  # 8 bytes
            if m_sVersion > 7:
                m_sPathName = cls.readbuf('<L')  # 4 bytes
            else:
                m_sPathName = cls.readbuf('H')  # 2 bytes
            m_pszName = cls.readstring()
            if DEBUG:
                print(elmdate, m_lLength, m_sPathName, m_pszName)
            m_paFileList.append((elmdate, m_lLength, m_sPathName, m_pszName))

        elm = m_paFileList

        cls.buffer.close()

        return cls(pathcatname, m_timeDate, m_strDevice, m_strVolume, m_strAlias, m_szVolumeName, m_dwSerialNumber, m_strComment, m_fFreeSize, m_sArchive, info, elm)

    @classmethod
    def fast_from_file(cls, pathcatname):
        # only reads the header info for freespace, archive bit etc.
        return cls.from_file(pathcatname, no_elm=True)

    def write(self, pathcatname):

        try:
            self.buffer = open(pathcatname, 'wb')
        except:
            return

        # m_sVersion - Check the magic
        ul = 3*CathyCat.ulModus+CathyCat.ulMagicBase

        if ul > 0 and ul % CathyCat.ulModus == CathyCat.ulMagicBase:
            m_sVersion = int(ul/CathyCat.ulModus)

        self.writebuf('<L', ul)
        self.writebuf('h', CathyCat.saveVersion)
        self.writebuf('<L', int(time.time()))

        self.writestring(self.device)
        self.writestring(self.volume)
        self.writestring(self.alias)

        t_serial = self.serial.replace('-', '')
        serial_long = int(t_serial, 16)
        self.writebuf('<L', serial_long)  # not sure if little endian is ok

        # m_strComment
        self.writestring(self.comment)
        self.writebuf('<f', self.freesize)

        # m_sArchive
        self.writebuf('h', self.archive)

        # folder information : file count, total size
        self.writebuf('<l', len(self.info))
        for i in range(len(self.info)):
            if i == 0:
                self.writestring("")
            # print(i,self.info[i][0],self.info[i][1])
            self.writebuf('<l', self.info[i][1])
            self.writebuf('<d', self.info[i][2])

        # files : date, size, parentfolderid, filename
        # if it's a folder :  date, -thisfolderid, parentfolderid, filename

        self.writebuf('<l', len(self.elm))
        for el in self.elm:
            self.writebuf('<L', el[0])  # date
            # print(el[1])
            self.writebuf('<q', el[1])  # size or folderid
            if self.saveVersion == 7:
                self.writebuf('H', el[2])  # parentfolderid
            else:
                self.writebuf('<L', el[2])  # parentfolderid
            self.writestring(el[3])  # filename

        self.buffer.close()

    def catpath(self):
        '''
        returns an absolute path to the main directory
        handled by this .cat file
        '''
        # return self.device + self.volume #[2:-1] # don't know why
        return self.volume

    def path(self, elmid):
        '''
        returns the absolute path of an element
        from its id or its name
        '''
        elmid = self._checkelmid(elmid)
        if type(elmid) == list:
            print('got several answers : %s\nselected the first id.' % elmid)
            elmid = elmid[0]

        pths = []
        while True:
            dt, lg, pn, nm = self.elm[elmid]
            pths.append(nm)
            # print(lg,pn,nm) # -368 302 cursors
            if pn == 0:
                pths.append(self.catpath())
                break
            else:
                for elmid, elm in enumerate(self.elm):
                    if elm[1] == -pn or elm[1] == pn:
                        # print('>',elm)
                        nm = elm[3]
                        break
                else:
                    nm = "ERRDIR"
                    print('error in parenting for ', pn, ', using "ERRDIR"')
                    break
        pths.reverse()
        # print(pths)
        return ospath.sep.join(pths)

    def parentof(self, elmid):
        '''
        returns the parent folder of an element,
        from its id or its name
        '''

        elmid = self._checkelmid(elmid)
        if type(elmid) == list:
            print('got several answers : %s\nselected the first id.' % elmid)
            elmid = elmid[0]

        dt, lg, pn, nm = self.elm[elmid]

        # a 0 parentid means it's the catalog 'root'
        if pn == 0:
            return self.catpath()
        # parent is a folder, it's id is in the size field, negated
        for i, elm in enumerate(self.elm):
            if elm[1] == -pn:
                return elm[3]

    def lookup_dir_id(self, elmid):
        FOUND = False
        tcnt = 0
        while not FOUND:
            if self.elm[tcnt][1] == -elmid:
                FOUND = True
            else:
                tcnt = tcnt + 1
        return tcnt

    def lookup(self, elmname):
        '''
        get an internal id from a file or folder name
        several answers are possible
        '''
        ids = []
        for i, elm in enumerate(self.elm):
            if elm[3] == elmname:
                ids.append(i)
        return ids[0] if len(ids) == 1 else ids

    # private
    def _checkelmid(self, elmid):
        if type(elmid) == str:
            elmid = self.lookup(elmid)
        return elmid

    # private. parser struct. fixed lengths
    @ classmethod
    def readbuf(cls, fmt, nb=False):
        if not(nb):
            nb = calcsize(fmt)
        return unpack(fmt, cls.buffer.read(nb))[0]

    # private. parser struct. fixed lengths
    def writebuf(self, fmt, inp):
        # if not(nb) : nb = calcsize(fmt)
        self.buffer.write(pack(fmt, inp))

    # private. parser string. arbitrary length. delimited by a 0 at its end
    @ classmethod
    def readstring_old(cls):
        chain = ''
        while 1:
            chr = cls.readbuf('s')
            if chr == CathyCat.delim:
                break
            else:
                try:
                    chain += chr.decode('unicode_escape')
                except:
                    pass
        return chain

    # private. parser string. arbitrary length. delimited by a 0 at its end
    @ classmethod
    def readstring(cls):
        chain = []
        while 1:
            chr = cls.buffer.read(1)
            if chr == CathyCat.delim:
                break
            else:
                try:
                    chain.append(chr)
                except:
                    pass
        return b''.join(chain).decode('latin1')

    def writestring(self, inp):
        if version_info[0] == 2:
            # some hack to allow the code to run on python2 and not crash on decode errors
            inp = inp.decode(errors='replace')
        # print(inp.encode('utf-8',errors='replace'))
        self.buffer.write(inp.encode('utf-8', errors='replace'))
        self.buffer.write(CathyCat.delim)

    @ classmethod
    def get_device(cls, start_path):
        # get the device from a mount path on linux
        output = subprocess.check_output(['df', start_path]).decode().split('\n')
        for line in output:
            if start_path in line:
                end = line.find(' ')
                device = line[:end]
        return device

    @ classmethod
    def get_serial(cls, start_path):
        if platform == "linux" or platform == "linux2":
            device = cls.get_device(start_path)
            output = subprocess.check_output(
                ['sudo', 'blkid', '-o', 'value', '-s', 'UUID', device]).decode().strip()
            ser = output[-8:-4]+"-"+output[-4:]
        elif platform == "darwin":
            output = subprocess.check_output(['diskutil', 'info', start_path]).decode()
            start = output.find("UUID:")+7
            end = output.find('\n', start)
            ser = output[end-8:end-4]+"-"+output[end-4:end]
        elif platform == "win32":
            output = subprocess.check_output(['vol', start_path], shell=True).decode().strip()
            ser = output[-9:]
        return ser

    @ classmethod
    def get_label(cls, start_path):
        if platform == "linux" or platform == "linux2":
            device = cls.get_device(start_path)
            output = subprocess.check_output(
                ['sudo', 'blkid', '-o', 'value', '-s', 'LABEL', device]).decode().strip()
            ser = output
        elif platform == "darwin":
            output = subprocess.check_output(['diskutil', 'info', start_path]).decode()
            start = output.find("Volume Name:")+12
            end = output.find('\n', start)
            ser = output[start:end].strip()
        elif platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volumeNameBuffer = ctypes.create_unicode_buffer(1024)
            fileSystemNameBuffer = ctypes.create_unicode_buffer(1024)
            serial_number = None
            max_component_length = None
            file_system_flags = None
            rc = kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(start_path),
                volumeNameBuffer,
                ctypes.sizeof(volumeNameBuffer),
                serial_number,
                max_component_length,
                file_system_flags,
                fileSystemNameBuffer,
                ctypes.sizeof(fileSystemNameBuffer)
            )
            ser = volumeNameBuffer.value
        return ser

    @ classmethod
    def get_free_space(cls, start_path):
        if platform == "linux" or platform == "linux2":
            output = subprocess.check_output(['df']).decode().split('\n')
            for line in output:
                if start_path in line:
                    items = [x for x in line.split(' ') if x]
                    ser = float(items[3])
        elif platform == "darwin":
            output = subprocess.check_output(['diskutil', 'info', start_path]).decode()
            start = output.find("Free Space:")
            start = output.find('(', start)+1
            end = output.find('Bytes', start)
            ser = float(output[start:end].strip())/1024
        elif platform == "win32":
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(
                start_path), None, None, ctypes.pointer(free_bytes))
            ser = float(free_bytes.value)/1024

        return ser/1024

    def scandir(self, dir_id, start_path):
        # the recursive function for scanning a disk
        # it is better to do the recursion yourself instead of using os.walk,
        # because then you can build the Cathy tree more easily (filecount and dirsize)
        tsize = 0
        filecnt = 0
        for el in os.listdir(start_path):
            elem = os.path.join(start_path, el)
            if os.path.isfile(elem):
                filecnt = filecnt + 1
                cursize = os.path.getsize(elem)
                tsize = tsize + cursize
                dat = os.path.getmtime(elem)
                self.elm.append((int(dat), cursize, dir_id, el))
            if os.path.isdir(elem):
                self.totaldirs = self.totaldirs + 1
                keepdir = self.totaldirs
                dat = os.path.getmtime(elem)
                self.elm.append((int(dat), -keepdir, dir_id, el))
                (did, fcnt, tsiz) = self.scandir(keepdir, elem)
                self.info.append((keepdir, fcnt, tsiz))
                filecnt = filecnt + fcnt
                tsize = tsize + tsiz
        return (dir_id, filecnt, tsize)

    @ classmethod
    def scan(cls, start_path, no_disk=False):
        # the scan function initializes the global caf parameters then calls the recursive scandir function
        pathcat = start_path		# catalogfilename in the cathy's ui
        date = int(time.time())		# caf creation date
        device = start_path			# for device now the start_path is used, for win this is prob drive letter, but for linux this will be the root dir
        if no_disk:
            volume = os.path.basename(start_path)
            serial = '0000-0000'
            freesize = 0
        else:
            volume = cls.get_label(start_path)
            serial = cls.get_serial(start_path)
            freesize = cls.get_free_space(start_path)
        alias = volume
        volumename = volume
        comment = ""
        archive = 0

        # init empty CathyCat class
        t_cat = cls(pathcat, date, device, volume, alias, volumename,
                    serial, comment, freesize, archive, [], [])
        t_cat.info.append(t_cat.scandir(0, start_path))
        t_cat.info.sort()

        return t_cat

    def getChildren(self, id):
        children = []
        for i in range(len(self.elm)):
            if self.elm[i][2] == id:
                if self.elm[i][1] < 0:
                    children.append((self.elm[i][3], int(
                        self.info[-self.elm[i][1]][2]), str(-self.elm[i][1])))
                else:
                    children.append((self.elm[i][3], int(self.elm[i][1]), ""))
        return children

# functions that use CathyCat


def makeCafList(path):
    # returns list of all .caf files in path using os.walk
    lst = []
    for fil in os.listdir(path):
        if ".caf" in fil[-4:]:
            lst.append(fil)
    return(lst)


def searchFor(pth, searchterm, archive=False):
    searchlist = searchterm.lower().split(' ')
    matches = []
    # checks all .caf files in patt for a match with alls terms in searchlist
    # archive option indicates if caf files with archive bit should be included in search
    if '.caf' in pth:
        cafList = [pth]
    else:
        cafList = makeCafList(pth)
    for catname in cafList:
        pathcatname = os.path.join(pth, catname)
        cat = CathyCat.fast_from_file(pathcatname)
        if cat.archive and not archive:
            print("Skipping", catname, "for search because of archive bit")
        else:
            cat = CathyCat.from_file(pathcatname)
            print(catname)
            for i in range(len(cat.elm)):
                FOUND = True
                for term in searchlist:
                    if version_info[0] == 2:
                        term = term.decode('utf-8').lower()
                    if not term in cat.elm[i][3].lower():
                        FOUND = False
                        break
                if FOUND:
                    print("Match:", cat.path(i))
                    if cat.elm[i][1] < 0:
                        matches.append((cat.path(i), int(cat.info[-cat.elm[i][1]][2])))
                    else:
                        matches.append((cat.path(i), cat.elm[i][1]))
    return matches


if __name__ == '__main__':

    # pth = os.getcwd() #path to .caf files
    pth = os.path.dirname(os.path.realpath(__file__))
    # print(pth)
    if len(argv) > 2:
        if "search" in argv[1]:
            searchFor(pth, argv[2])

        elif "dirscan" in argv[1]:
            scanpath = argv[2]
            scanpath = os.path.normpath(scanpath)
            # if scanpath[-1] == '/' or scanpath[-1] == '\\':
            #	scanpath = scanpath[:-1]
            print("Scanning:", scanpath, "...")
            cat = CathyCat.scan(scanpath, no_disk=True)
            if "archive" in argv[1]:
                print("Setting archive bit!")
                cat.archive = 1
            savename = os.path.join(os.getcwd(), cat.volume+".caf")
            print("Saving to:", savename)
            cat.write(savename)

        elif "scan" in argv[1]:
            scanpath = argv[2]
            scanpath = os.path.normpath(scanpath)
            # if scanpath[-1] == '/' or scanpath[-1] == '\\':
            #	scanpath = scanpath[:-1]
            print("Scanning:", scanpath, "...")
            cat = CathyCat.scan(scanpath)
            if "archive" in argv[1]:
                print("Setting archive bit!")
                cat.archive = 1
            savename = os.path.join(os.getcwd(), cat.volume+".caf")
            print("Saving to:", savename)
            cat.write(savename)

        elif "setarchive" in argv[1]:
            setpath = os.path.join(pth, argv[2])
            cat = CathyCat.from_file(setpath)
            cat.archive = 1
            cat.write(setpath)

        elif "export" in argv[1]:
            setpath = os.path.join(pth, argv[2])
            cat = CathyCat.from_file(setpath)
            with open(setpath.replace(".caf", ".csv"), "w") as fp:
                for i in range(len(cat.elm)):
                    if cat.elm[i][1] > 0:
                        # print(cat.elm[i][3])
                        fp.write(cat.elm[i][3]+'\t'+str(cat.elm[i][1])+'\t' +
                                 cat.path(i).replace(cat.elm[i][3], '')+'\n')

    elif len(argv) == 2:
        if "usage" in argv[1]:
            cafList = makeCafList(pth)
            lst = []
            for catname in cafList:
                pathcatname = os.path.join(pth, catname)
                cat = CathyCat.fast_from_file(pathcatname)
                free = int(cat.freesize/1000)
                used = int(int(cat.info[0][2])/1000/1000/1000)
                lst.append((free, catname, used))
            for item in sorted(lst):
                print("{0:12}\tFree:\t{1:>5}Gb\t\tUsed:\t{2:>5}Gb\t\tTotal:\t{3:>3.1f}Tb".format(
                    item[1].replace(".caf", "")[:12], item[0], item[2], float(item[0]+item[2])/1000))

    else:
        print("Not enough arguments.\nUse 'python cathy.py search <term>' to search and 'python cathy.py scan <path>' to scan a device.")
