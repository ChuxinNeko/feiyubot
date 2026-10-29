"""飞鱼入口。在仓库根目录执行：python bot.py"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


def _load_env() -> None:
    load_dotenv(".env")
    data_dir = Path(os.environ.get("FEIYU_DATA_DIR", "data"))
    runtime = data_dir / "runtime.env"
    if runtime.exists():
        load_dotenv(runtime, override=True)


_load_env()
nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)


@driver.on_startup
async def _startup() -> None:
    from feiyubot.service import init_service
    from feiyubot.web.api import install

    service = init_service()
    app = driver.server_app
    assert app is not None
    install(app, service)
    import asyncio

    asyncio.get_running_loop().create_task(_proactive())
    password_file = service.data_dir / "admin_password.txt"
    if password_file.exists():
        nonebot.logger.info(f"管理密码写在 {password_file} ，登录 WebUI 后请尽快修改")
    nonebot.logger.info("WebUI: http://{}:{}/", driver.config.host, driver.config.port)


@driver.on_shutdown
async def _shutdown() -> None:
    from feiyubot.service import get_service

    try:
        await get_service().aclose()
    except RuntimeError:
        return


async def _proactive() -> None:
    import asyncio

    await asyncio.sleep(180)
    while True:
        try:
            from feiyubot.ling.proactive import tick
            from feiyubot.service import get_service

            await tick(get_service())
        except Exception:
            nonebot.logger.debug("主动找人这一轮跳过")
        await asyncio.sleep(600)


nonebot.load_plugin("feiyubot.plugins.chat")

if __name__ == "__main__":
    nonebot.run()
