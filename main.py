import hashlib
import logging
import random
import sys
import requests
import re
import time
from multiprocessing.dummy import Pool as ThreadPool
from threading import Lock
from bs4 import BeautifulSoup
from config import Config

lock = Lock()
pool = ThreadPool(100)
is_frequent = False
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/74.0'}
cf = Config('config.ini', '配置')


def create_weibo(text, cid):
    """
    创建微博
    :param text: 内容
    :param cid: 超话id
    :return:
    """
    headers = {'Referer': 'https://weibo.com'}
    cookies = {'SUB': gsid}
    data = {
        'text': text, 'sync_wb': '1',
        'api': f'http://i.huati.weibo.com/pcpage/operation/publisher/sendcontent?sign=super&page_id={cid}',
        'topic_id': f'1022:{cid}'}
    url = 'https://weibo.com/p/aj/proxy?ajwvr=6'
    r = requests.post(url, data=data, cookies=cookies, headers=headers)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code) + ':' + r.text)
    if r.json()['code'] == '100000':
        mid = r.json()['data']['mid']
        cf.Add('配置', 'mid', mid)
        cf.Add('配置', 'time', str(time.time()))
        return mid
    else:
        print(r.json()['msg'])
        return False


def comment(args):
    """
    评论微博
    :param args:
    :return:
    """
    global com_suc_num
    global is_frequent
    mid, content = args
    detail_url = 'https://m.weibo.cn/detail/' + mid
    if get_mid_num() >= comment_max:
        print(f'你已经评论{comment_max}条了')
        exit()
    if mid_in_file(mid):
        with lock:
            print('你已经评论：' + detail_url)
        return
    cookies = {'SUB': gsid}
    while True:
        try:
            r = requests.get(detail_url, cookies=cookies, timeout=2)
            r.encoding = 'utf-8'
            logging.info(str(r.status_code))
            if r.status_code == 200:
                break
            elif r.status_code == 418:
                time.sleep(0.5)
            elif r.status_code == 403:
                return
        except:
            pass
    if f'"id": {uid}' in r.text:
        print('已跳过评论自己的微博：' + detail_url)
        mid_write_file(mid)
        return
    st = r.cookies.get_dict()['XSRF-TOKEN']
    cookies.update(r.cookies.get_dict())
    url = 'https://m.weibo.cn/api/comments/create'
    data = {'content': content, 'mid': mid, 'st': st}
    while True:
        try:
            r = requests.post(url, data=data, cookies=cookies, timeout=1)
            r.encoding = 'utf-8'
            try:
                logging.info(str(r.status_code) + ':' + str(r.json()))
            except:
                logging.warning(str(r.status_code))
            break
        except:
            pass
    try:
        if r.json()['ok'] == 1:
            with lock:
                print('评论成功：' + detail_url)
            mid_write_file(mid)
            com_suc_num += 1
            return
        else:
            with lock:
                print('评论失败：' + detail_url)
                if r.json()['ok'] == 0:
                    print(r.json()['msg'])
                    # 频繁
                    if r.json()['errno'] == '100005':
                        is_frequent = True
                    # 已经评论
                    elif r.json()['errno'] == '20019':
                        mid_write_file(mid)
                    # 只允许粉丝评论
                    elif r.json()['errno'] == '20210':
                        pass
                    # 发微博太多
                    elif r.json()['errno'] == '20016':
                        pass
            return
    except:
        with lock:
            print('评论失败：' + detail_url)
        if r.json()['errno'] == '100005':
            is_frequent = True
        return


def after_zoro(t):
    """
    判断是否是当天零点后发布的
    :param t:
    :return:
    """
    if t == '刚刚':
        return True
    elif re.match('^(\d{1,2})分钟前$', t):
        if int(t[:-3]) * 60 < int(time.time() - time.timezone) % 86400:
            return True
    elif re.match('^(\d{1,2})小时前$', t):
        if int(t[:-3]) * 3600 < int(time.time() - time.timezone) % 86400:
            return True
    return False


def mid_write_file(mid):
    """
    记录已经评论的mid
    :param mid:
    :return:
    """
    with open('mid.txt', 'r') as f:
        if mid not in f.read():
            with open('mid.txt', 'a') as f1:
                f1.write(mid + '\n')


def mid_in_file(mid):
    """
    判断mid是否已经评论
    :param mid:
    :return:
    """
    open('mid.txt', 'a').close()  # 防止不存在时报错
    with open('mid.txt', 'r') as f:
        return mid in f.read()


def clear_mid_file():
    """
    清除mid文件
    :return:
    """
    open('mid.txt', 'w').close()


def clear_log():
    """
    清除log文件
    :return:
    """
    open('weibo.log', 'w').close()


def get_mid_num():
    count = 0
    with open('mid.txt', 'r') as f:
        for i in f.read().split('\n'):
            if i != '':
                count += 1
    return count


def get_mid(cid, page=1):
    """
    获取帖子
    :param cid: 超话id
    :param page: 页数
    :return: 帖子列表
    """
    global is_frequent

    def analysis_and_join_list(mblog):
        t = mblog['created_at']
        mid = mblog['mid']
        user_id = str(mblog['user']['id'])
        if not after_zoro(t):
            return
        if mid != my_mid and not mid_in_file(mid) and user_id != uid:
            mid_list.append((mid, user_id))
            screen_name = mblog['user']['screen_name']
            print(screen_name.strip().replace('\n', ''), t, mid, user_id)
            return True
        else:
            return False

    mid_list = []
    since_id = ''
    start_page = 0
    if re.match('\d+ \d+', str(page)):
        start_page = int(page.split()[0])
        page = int(page.split()[1])
    else:
        page = int(page)
    req = requests.Session()
    req.headers = headers
    i = 0  # 爬取成功页数
    p = 0  # 已爬取页数
    while i < page:
        length = len(mid_list)
        with lock:
            print('*' * 100)
            print('第%d页' % (p + 1))
        url = f'https://m.weibo.cn/api/container/getIndex?containerid={cid}_-_sort_time' + since_id
        while True:
            try:
                r = req.get(url, timeout=2)
                r.encoding = 'utf-8'
                logging.info(str(r.status_code))
                if r.status_code == 200 and r.json()['ok'] == 1:
                    break
                # 反爬
                elif r.status_code == 418:
                    is_frequent = True
                    return mid_list
                elif r.status_code == 502:
                    time.sleep(0.5)
            except:
                pass
        card_page = 0
        if p + 1 >= start_page:
            # 判断是否是第一页
            if r.json()['data']['cards'][0]['card_group'][0]['card_type'] == '121':
                card_page = 1
                mblog = r.json()['data']['cards'][0]['card_group'][1]['mblog']
                if analysis_and_join_list(mblog) is None:
                    return mid_list
            for j in r.json()['data']['cards'][card_page]['card_group']:
                mblog = j['mblog']
                if analysis_and_join_list(mblog) is None:
                    return mid_list
        since_id = '&since_id=' + str(r.json()['data']['pageInfo']['since_id'])
        if length < len(mid_list):
            i += 1
        p += 1
        if p >= get_mid_max:
            break
    return mid_list


def get_my_mid():
    """
    获取配置中自己的帖子
    :return:
    """
    mid = cf.GetStr('配置', 'mid')
    if mid == '':
        return False
    return mid


def get_gsid():
    """
    获取gsid
    :return:
    """
    gsid = cf.GetStr('配置', 'gsid')
    if gsid == '':
        print('请前往"https://m.weibo.cn"获取gsid')
        gsid = input('请输入你的gsid：')
        cf.Add('配置', 'gsid', gsid)
    return gsid


def is_today():
    """
    获取配置中的信息的时间
    :return: bool
    """
    t = cf.GetFloat('配置', 'time')
    zoro_time = int(time.time()) - int(time.time() - time.timezone) % 86400
    if t != None and t >= zoro_time:
        return True
    else:
        return False


def get_uid(gsid):
    """
    获取用户的id
    :param gsid:
    :return:
    """
    global is_frequent
    req = requests.Session()
    cookies = {'SUB': gsid}
    url = 'https://m.weibo.cn/api/config'
    while True:
        r = req.get(url, cookies=cookies)
        r.encoding = 'utf-8'
        try:
            logging.info(str(r.status_code) + ':' + str(r.json()))
        except:
            logging.warning(str(r.status_code))
        if r.status_code == 200:
            break
        elif r.status_code == 502:
            time.sleep(0.5)
        elif r.status_code == 418:
            is_frequent = True
            return
        elif r.status_code == 403:
            is_frequent = True
            return
    try:
        return r.json()['data']['uid']
    except:
        if not r.json()['data']['login']:
            print('请重新登录')
            cf.Del('配置', 'gsid')
            exit()
        elif r.json()['ok'] == 0:
            print(r.json()['msg'])
            if r.json()['errno'] == '100005':
                is_frequent = True
        return


def find_super_topic(name):
    """
    通过超话名字找超话id
    :param name: 超话名字
    :return:
    """
    url = 'https://m.weibo.cn/api/container/getIndex?containerid=100103type=1%26q=' + name
    r = requests.get(url)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    return re.findall('100808[\d\w]{32}', r.text)[0]


def get_bid(mid):
    """
    获取帖子的bid
    bid链接群聊不会被转换成短链
    :param mid: 帖子id
    :return:
    """
    url = 'https://m.weibo.cn/detail/' + mid
    r = requests.get(url)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    bid = re.findall('"bid": "(.*?)"', r.text)[0]
    return bid


def group_chat_comments(gid):
    """
    群聊评论信息
    :param gid: 群id
    :return:
    """
    cookies = {'SUB': gsid}
    headers = {'referer': 'https://m.weibo.cn'}

    # 获取uid
    uid = get_uid(gsid)

    # 获取bid
    bid = get_bid(my_mid)

    # 获取st,群信息
    url = 'https://m.weibo.cn/api/groupchat/list?gid=' + gid
    r = requests.get(url, cookies=cookies, headers=headers)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    title = r.json()['data']['title']
    num = re.findall('\((.*?)\)', title)[0]
    title = re.findall('(.*?)\(.*?\)', title)[0]
    print('正在发送群聊：' + title)
    print('群人数：' + num)
    st = r.cookies.get_dict()['XSRF-TOKEN']
    cookies.update(r.cookies.get_dict())

    # 评论
    url = 'https://m.weibo.cn/api/groupchat/send'
    data = {'content': f'http://weibo.com/{uid}/{bid}', 'gid': gid, 'st': st}
    r = requests.post(url, cookies=cookies, data=data, headers=headers)
    if r.json()['ok'] == 1:
        print('发送成功：' + title)
    else:
        print('发送失败：' + title)


def vip_sign(gsid):
    """
    每日vip签到成长值
    :param gsid:
    :return:
    """
    url = 'https://new.vip.weibo.cn/aj/task/qiandao?task_id=1&F=growth_yhzx_didao'
    cookies = {'SUB': gsid}
    headers = {
        'Referer': 'https://new.vip.weibo.cn'}
    req = requests.Session()
    r = req.get(url, headers=headers, cookies=cookies)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    print(r.json()['msg'])


def vip_pk(gsid):
    """
    每日vip pk任务
    :param gsid:
    :return:
    """
    req = requests.Session()
    url = 'https://new.vip.weibo.cn/task/pk?from_pk=1&task_id=66'
    cookies = {'SUB': gsid}
    headers = {
        'Referer': 'https://new.vip.weibo.cn'}

    # 获取pk对象
    r = req.get(url, headers=headers, cookies=cookies)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    soup = BeautifulSoup(r.text, 'html.parser')
    card = []
    for i in soup.find_all('div', class_='card line-around card10'):
        name = i.text.strip()
        action = i['action-data']
        card.append({'name': name, 'action': action})

    # 随机选择一个pk
    card = random.choice(card)
    name = card['name']
    action = card['action']
    print('正在pk：' + name)

    # 获取pk结果
    url = f'https://new.vip.weibo.cn/pk?uid={action}&task_id=66&from=from_task_pk'
    r = req.get(url, headers=headers, cookies=cookies)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    soup = BeautifulSoup(r.text, 'html.parser')
    try:
        isWin1 = re.findall('value="(.*)" id="isWin1"', r.text)[0] != ''
        isWin2 = re.findall('value="(.*)" id="isWin2"', r.text)[0] != ''
    except:
        print(r.json()['msg'])
        return False
    if isWin1 and not isWin2:
        # 胜利
        win = 1
        flag = 1
    elif not isWin1 and isWin2:
        # 失败
        win = 3
        flag = 0
    else:
        # 平局
        win = 2
        flag = 3
    for i, j in enumerate(soup.find_all('div', class_='PK_layerbase'), 1):
        if i == win:
            print(j.find('header').text.strip())
    url = f'https://new.vip.weibo.cn/aj/pklog'
    data = {'duid': action, 'flag': flag, 'F': ''}
    r = req.post(url, headers=headers, cookies=cookies, data=data)
    print(r.json()['msg'])


def sign_integral(gsid):
    """
    连续访问积分
    访问1天 +3
    连续访问2天以上 +5
    连续访问8天及以上 +8
    :param gsid:
    :return:
    """
    url = 'https://huati.weibo.cn/aj/super/receivescore'
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://huati.weibo.cn'}
    cookies = {'SUB': gsid}
    data = {'type': 'REQUEST', 'user_score': 999}
    r = requests.post(url, headers=headers, data=data, cookies=cookies)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    print(r.json()['msg'])


def push_wechat(text, desp):
    """
    推送信息到微信
    :param text: 标题
    :param desp: 内容
    :return:
    """
    if SCKEY == '':
        return False
    data = {'text': text, 'desp': desp}
    try:
        r = requests.post(f'https://sc.ftqq.com/{SCKEY}.send', data=data)
        r.encoding = 'utf-8'
        try:
            logging.info(str(r.status_code) + ':' + str(r.json()))
        except:
            logging.warning(str(r.status_code))
        if r.json()['errno'] == 0:
            return True
        else:
            return False
    except:
        return False


def get_st(parmas, gsid):
    """
    微博超话客户端的参数加密验证
    :param parmas:
    :param gsid:
    :return:
    """
    KEY = 'SloRtZ4^OfpVi!#3u!!hmnCYzh*fxN62Nyy*023Z'
    str = ''
    for i in parmas:
        str += i + ':' + parmas[i] + ','
    str = str + gsid + KEY
    m = hashlib.md5()
    m.update(str.encode())
    str = m.hexdigest()
    st = ''
    for i in range(0, len(str), 2):
        st += str[i]
    return st


def login_integral(gsid):
    """
    超话登录积分 +10
    :param gsid:
    :return:
    """
    parmas = {'from': '21A3095010', 'ti': str(int(time.time() * 1000))}
    st = get_st(parmas, gsid)
    headers = {'gsid': gsid, 'st': st}
    r = requests.get('https://chaohua.weibo.cn/remind/active', params=parmas, headers=headers)
    r.encoding = 'utf-8'
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    if r.json()['code'] == 100000:
        return True
    return False


def init_log(level):
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(pathname)s->%(funcName)s line %(lineno)d : %(message)s"
    DATE_FORMAT = "%m/%d/%Y %H:%M:%S %p"
    logging.basicConfig(handlers=[logging.FileHandler('weibo.log', 'a', 'utf-8')], level=level, format=LOG_FORMAT,
                        datefmt=DATE_FORMAT)


def start_comments():
    global com_suc_num
    global is_frequent
    mid_list = get_mid(cid, get_mid_page)
    mid_lists = []
    for mid, user_id in mid_list:
        if user_id in custom_comments.keys():
            content = custom_comments[user_id].format(mid=mid)
        else:
            content = default_content.format(mid=mid)
        mid_lists.append((mid, content))
    com_suc_num = 0
    print('开始评论')
    try:
        pool.map(comment, mid_lists)
    except:
        is_frequent = True
    print('评论成功数：' + str(com_suc_num))
    push_wechat('weibo_comments', f'''
                {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
                评论成功数：{com_suc_num}''')


def loop_comments(num):
    global uid
    global is_frequent
    for i in range(num):
        get_uid(gsid)
        if get_mid_num() >= comment_max:
            print(f'你已经评论{comment_max}条了')
            exit()
        if is_frequent:
            n = frequent_wait_time
            push_wechat('weibo_comments', f'''
                        {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
                        请求过于频繁,正在等待{n}秒''')
            while n + 1:
                time.sleep(1)
                sys.stdout.write(f'\r等待时间：{n}秒')
                n -= 1
            print()
            is_frequent = False
        else:
            n = comments_wait_time
        while n + 1:
            time.sleep(1)
            sys.stdout.write(f'\r等待时间：{n}秒')
            n -= 1
        sys.stdout.write(f'\r第{i + 1}次，开始获取微博\n')
        push_wechat('weibo_comments', f'''
            {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
            第{i + 1}次，开始获取微博''')
        start_comments()


if __name__ == '__main__':
    get_mid_page = 5  # 一次爬微博页数
    get_mid_max = 10  # 爬取失败时最多爬取的页数
    comment_max = 1000  # 最多评论次数
    loop_comments_num = 10  # 运行次数
    comments_wait_time = 10  # 每次延迟运行时间
    frequent_wait_time = 600  # 频繁等待时间
    # 微信推送 http://sc.ftqq.com
    SCKEY = ''
    # 评论的超话
    st_name = '橘子工厂'
    # 需要发送的群聊的id
    gid_list = [

    ]
    # 默认评论内容
    default_content = 'https://m.weibo.cn/detail/{mid}'
    # 自定义评论内容
    custom_comments = {
        # uid:评论内容
    }
    init_log(logging.INFO)
    gsid = get_gsid()
    uid = get_uid(gsid)
    cid = find_super_topic(st_name)
    if is_today():
        print('正在读取微博')
        my_mid = get_my_mid()
        if not my_mid:
            print('读取失败')
            exit()
        else:
            print('读取成功')
    else:
        print('正在创建微博')
        my_mid = create_weibo(f'#{st_name}[超话]#积分！', cid)
        if my_mid == False:
            print('创建失败')
            exit()
        else:
            print('创建成功')
            # 发送微博到群聊
            for gid in gid_list:
                group_chat_comments(gid)
        print('*' * 100)
        print('开始：vip签到')
        vip_sign(gsid)
        print('*' * 100)
        print('开始：vip pk')
        vip_pk(gsid)
        print('*' * 100)
        print('开始：超话登录积分')
        login_integral(gsid)
        print('*' * 100)
        print('开始：每日签到积分')
        sign_integral(gsid)
        print('*' * 100)
        clear_log()
        clear_mid_file()
    print('https://m.weibo.cn/detail/' + my_mid)
    loop_comments(loop_comments_num)
