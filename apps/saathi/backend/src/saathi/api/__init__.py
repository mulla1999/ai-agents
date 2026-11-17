from . import admin, applications, auth, chat, citizens, schemes

ROUTERS = (auth.router, citizens.router, chat.router, applications.router, schemes.router, admin.router)
