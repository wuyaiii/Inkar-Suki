
from ... import *


def test_horse_loader():
    import src.plugins.jx3.horse.v2
    result = asyncio.run(src.plugins.jx3.horse.v2.get_horse_reporter('唯我独尊'))
    assert len(result) > 0


def test_horse_list_view():
    mc = MessageCallback()
    import src.plugins.jx3.horse.v2
    src.plugins.jx3.horse.v2.jx3_cmd_horseinfo_map = mc

    func = src.plugins.jx3.jx3_horse
    event = SFGroupMessageEvent()

    mc.tag = '唯满侠'
    task = func(event, obMessage(mc.tag))
    asyncio.run(task)
    mc.check_counter()
