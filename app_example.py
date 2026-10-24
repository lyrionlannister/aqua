from . import Aqua, Module

@Module
class AppModule():
    pass



app = Aqua(root_module=AppModule())