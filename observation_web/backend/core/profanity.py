"""
Nickname profanity compliance checks.
"""

from __future__ import annotations

_CN_WORDS = frozenset({
    "操", "艹", "妈的", "卧槽", "去死", "滚",
    "傻", "傻逼", "傻比", "蠢", "弱智", "智障", "脑残", "白痴", "废物", "垃圾",
    "人渣", "菜鸡", "菜狗", "贱", "贱人", "婊", "婊子",
    "骚", "下流", "恶心", "狗东西", "猪头", "畜生", "杂种", "王八", "王八蛋",
    "孙子", "儿子", "爸爸", "爹", "老子", "大爷", "爷", "小崽子",
    "狗日", "狗娘养", "你大爷", "死全家",
    "嫖", "嫖娼", "妓女", "援交", "约炮",
    "宝贝", "亲爱的", "小骚", "亲亲", "么么哒",
    "sb", "2b", "二逼", "装逼", "牛逼", "沙雕",
    "神经病", "精神病", "有病", "土鳖", "乡巴佬", "穷鬼", "乞丐",
    "臭不要脸", "不要脸", "无耻", "卑鄙", "下贱", "丑八怪", "丑逼", "死胖子", "娘炮",
})

_EN_WORDS = frozenset({
    "fuck", "fuk", "f***", "shit", "bullshit", "crap",
    "ass", "asshole", "dick", "bitch", "bastard",
    "slut", "whore", "hoe", "jerk", "idiot", "stupid", "moron", "retard", "dumb",
    "trash", "loser", "sucker", "scum", "pig", "dog", "freak", "pervert", "nasty",
    "filthy", "ugly", "fatass", "lame", "pathetic",
    "kill yourself", "kys", "go die", "shut up",
    "dirty", "silly clown", "creep", "psycho", "lunatic", "insane",
})


def check_nickname(nickname: str) -> tuple[bool, str]:
    name = (nickname or "").strip().lower()
    if not name:
        return False, "昵称不能为空"
    for word in _CN_WORDS:
        if word in name:
            return False, "包含不当词汇"
    for word in _EN_WORDS:
        if word in name:
            return False, "包含不当词汇"
    return True, ""

