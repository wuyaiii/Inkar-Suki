from __future__ import annotations
from src.tools.dep.args import Jx3ArgsType
from ..DocumentCatalog import permission, BaseCatalog
from .DocumentItem import DocumentItem
from .converter import *
from ...group_env import *
from src.tools.utils import *


class CommandRecordStatus(enum.IntFlag):
    normal = 1
    disabled = 2


class CommandRecord:
    name: str = None  # 名称
    favorite: int = 0  # 热度
    enable: bool = True  # 是否启用

    cache_db: dict[str, filebase_database.Database] = {}

    @staticmethod
    def reduce_popularity_single(db: filebase_database.Database):
        commands = db.value
        counter = 0
        wait_to_remove = []
        for command in commands:
            cmd = commands[command]
            prev = cmd.get('favorite')
            if prev is None:
                continue
            counter += 1
            prev *= 0.995  # 每次降低5‰
            prev -= 1  # 并-1
            if prev < 0:
                wait_to_remove.append(command)
        for command in wait_to_remove:
            del commands[command]
        return counter, len(wait_to_remove)

    @staticmethod
    def reduce_popularity():
        counter = 0
        remove_count = 0
        for db_path in CommandRecord.cache_db:
            db = CommandRecord.cache_db.get(db_path)
            s_counter, s_remove_count = CommandRecord.reduce_popularity_single(db)
            counter += s_counter
            remove_count += s_remove_count

        msg = 'completed reduce_popularity'
        if remove_count:
            msg = f'{msg} removed:{remove_count}'
        logger.debug(f"{msg} count:{counter}")

    @staticmethod
    def get_db(group: str = None) -> filebase_database.Database:
        path = bot_path.DATA
        suffix = group or bot_path.common_data
        path = f'{path}{os.sep}{suffix}{os.sep}commands'

        prev = CommandRecord.cache_db.get(path)
        if prev:
            return prev
        db: filebase_database.Database = filebase_database.Database(path)
        CommandRecord.cache_db[path] = db
        return db

    @staticmethod
    def get_sts(caller_name: str, group: str = None, new_sts: CommandRecord = None) -> CommandRecord:
        '''统计功能使用'''

        db = CommandRecord.get_db(group)
        if new_sts:
            if isinstance(new_sts, CommandRecord):
                new_sts = new_sts.to_dict()
            db.value[caller_name] = new_sts
            return new_sts

        if not db.value.get(caller_name):
            db.value[caller_name] = CommandRecord().to_dict()
        sts: CommandRecord = clazz.dict2obj(CommandRecord(), db.value.get(caller_name))
        return sts

    @staticmethod
    def record(caller_name: str, group: str = None, favorite: int = 10) -> CommandRecordStatus:
        sts: CommandRecord = CommandRecord.get_sts(caller_name, group)
        sts.favorite += favorite

        CommandRecord.get_sts(caller_name, group, sts)  # 存回

        GroupActivity(group).update_command(1)
        if not sts.enable:
            return CommandRecordStatus.disabled
        return CommandRecordStatus.normal

    def to_dict(self):
        return {
            'favorite': self.favorite,
            'enable': self.enable,
        }


class DocumentGenerator:
    commands: dict[str, DocumentItem] = {}
    _document: dict = None
    _doc_lock = threading.Lock()

    @staticmethod
    def register_single(arg: AssignableArg):
        cmd = arg.args[0]
        docs = DocumentItem(cmd, arg)
        DocumentGenerator.commands[cmd] = docs
        return docs

    @staticmethod
    def register(method: callable):
        '''注册到帮助文档
        此处注册的名字为命令名称，需要保证名称与函数名一致'''
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            arg = AssignableArg(args=args, kwargs=kwargs, method=method)
            if 'regex' in method.__name__:  # 重写正则
                x = DocumentGenerator.get_regex(args[0])
                arg.set_args(0, x)
            _ = DocumentGenerator.register_single(arg)
            result = method(*arg.args, **arg.kwargs)
            # logger.debug(f'docs:{docs}') # 显示很慢
            return result
        return wrapper

    @staticmethod
    def record(method: callable):
        '''记录每次指令调用'''
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            args = AssignableArg(args, kwargs, method)

            raw_input, _ = args.check_if_exist('raw_input')
            raw_input = convert_to_str(raw_input)
            args.set_args(0, raw_input)

            result = method(*args.args, **args.kwargs)
            status: CommandRecordStatus = DocumentGenerator._record_log(args, result)
            if status & status.disabled == status.disabled:
                return None
            return result
        return wrapper

    @staticmethod
    def _record_log(args: AssignableArg, result: list[any]) -> CommandRecordStatus:
        method, _ = args.check_if_exist('method')
        raw_input, _ = args.check_if_exist('raw_input')
        event, _ = args.check_if_exist('event')

        if method:
            caller_name = method if isinstance(method, str) else method.__name__
        else:
            method_names = [x[3] for x in inspect.stack()]
            caller_name_pos = extensions.find(enumerate(method_names), lambda x: x[1] == 'get_args')
            caller_name = method_names[caller_name_pos[0] + 1]

        group = event and event.group_id
        log = {
            'name': caller_name,
            'args': result,
            'raw': raw_input,
            'group': group,
            'user': event and event.user_id,
        }

        # 记录和检查
        msg_status = ''
        s_global = CommandRecord.record(caller_name)
        s_group = CommandRecord.record(caller_name, group) if group else CommandRecordStatus.normal
        if s_global & CommandRecordStatus.disabled == CommandRecordStatus.disabled:
            msg_status = '-global-disabled'
        elif s_group & CommandRecordStatus.disabled == CommandRecordStatus.disabled:
            msg_status = '-group-disabled'
        logger.debug(f'func_called{msg_status}:{log}')
        return CommandRecordStatus.disabled if msg_status else CommandRecordStatus.normal  # TODO 策略模式包装

    @staticmethod
    def get_regex(pattern: str):
        # 精确匹配
        if not pattern[-1] == '$':
            return f'{pattern}($| )'

        # 和常规匹配
        return pattern

    @staticmethod
    def counter(method: callable):
        # TODO 不会写
        '''TODO 用户每次使用时调用'''
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            result = method(*args, **kwargs)
            logger.debug(f'功能调用:{args},{kwargs}')
            return result
        return wrapper

    @staticmethod
    def _get_documents() -> dict:
        catalogs = permission.to_dict()
        commands = [DocumentGenerator.commands[x].to_dict() for x in DocumentGenerator.commands]
        args_template = dict([[x.name, x.to_dict()] for x in Jx3ArgsType])

        return {
            'catalogs': catalogs,
            'commands': commands,
            'args_template': args_template,
        }

    @staticmethod
    def get_documents() -> dict:
        '''获取文档数据'''
        with DocumentGenerator._doc_lock:
            if DocumentGenerator._document:
                return DocumentGenerator._document
            DocumentGenerator._document = DocumentGenerator._get_documents()
            return DocumentGenerator._document
