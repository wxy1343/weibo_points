import configparser

# 配置处理类
class Config:
    __configdir = False

    def __init__(self, configdir='', section=None):
        # 默认为空
        if not configdir.strip():
            self.__configdir = "config.ini"
        else:
            self.__configdir = configdir
        self.cf = configparser.ConfigParser()
        open(self.__configdir, 'a').close()
        if section != None:
            self.cf.add_section(section)
        return

    # 获取配置数据
    # string
    def GetStr(self, section, option):
        try:
            self.cf.read(self.__configdir)
            Ret = self.cf.get(section, option)
            return Ret
        except Exception:
            return ""

    # int
    def GetInt(self, section, option):
        try:
            self.cf.read(self.__configdir)
            Ret = self.cf.getint(section, option)
            return Ret
        except Exception:
            return None

    # float
    def GetFloat(self, section, option):
        try:
            self.cf.read(self.__configdir)
            Ret = self.cf.getfloat(section, option)
            return Ret
        except Exception:
            return None

    # bool
    def GetBool(self, section, option):
        try:
            self.cf.read(self.__configdir)
            Ret = self.cf.getboolean(section, option)
            return Ret
        except Exception:
            return False

    # 修改数据
    def Update(self, section, option, value):
        try:
            self.cf.read(self.__configdir)
            if self.option != option:
                self.cf.set(section, option, value)
            self.cf.write(open(self.__configdir, "r+"))
            return True
        except Exception:
            return False

    # 添加数据
    def Add(self, section, option, value):
        try:
            self.cf.read(self.__configdir)
            self.cf.set(section, option, value)
            self.cf.write(open(self.__configdir, "r+"))
            return True
        except Exception:
            return False

    # 删除数据
    def Del(self, section, option):
        try:
            self.cf.remove_option(section, option)
            self.cf.write(open(self.__configdir, "w"))
            return True
        except Exception:
            return False
