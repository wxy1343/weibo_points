import hashlib
import logging
import random
import re
import sys
import time
import traceback
from multiprocessing.dummy import Pool
from threading import Lock

import requests
from bs4 import BeautifulSoup

from config import Config

lock = Lock()
pool = Pool(100)
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

    def add_config():
        cf.Add('配置', 'mid', mid)
        cf.Add('配置', 'time', str(time.time()))

    def retry():
        for info in get_weibo_info(gsid):
            mid = info['mid']
            title = info['title']
            if title == weibo_title:
                add_config()
                return mid
        else:
            print('创建微博失败,正在重试')
            time.sleep(0.1)
            mid = create_weibo(text, cid)
            return mid

    headers = {'Referer': 'https://weibo.com'}
    cookies = {'SUB': gsid}
    data = {
        'text': text, 'sync_wb': '1',
        'api': f'http://i.huati.weibo.com/pcpage/operation/publisher/sendcontent?sign=super&page_id={cid}',
        'topic_id': f'1022:{cid}'}
    url = 'https://weibo.com/p/aj/proxy?ajwvr=6'
    r = requests.post(url, data=data, cookies=cookies, headers=headers)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code) + ':' + r.text)
        return retry()
    if r.json()['code'] == '100000':
        mid = r.json()['data']['mid']
        add_config()
        return mid
    elif r.json()['code'] == '20019':
        return retry()
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
        with lock:
            print(f'你已经评论{comment_max}条了')
            exit()
    if mid_in_file(mid):
        with lock:
            print('你已经评论：' + detail_url)
        return
    cookies = {'SUB': gsid}
    wait_time = 0.5
    while True:
        try:
            if wait_time >= 8:
                is_frequent = True
                return False
            r = requests.get(detail_url, cookies=cookies)
            logging.info(str(r.status_code))
            if r.status_code == 200:
                break
            elif r.status_code == 418:
                time.sleep(wait_time)
            elif r.status_code == 403:
                with lock:
                    print('评论失败：' + detail_url)
                return False
            wait_time *= 2
        except:
            pass
    st = r.cookies.get_dict()['XSRF-TOKEN']
    cookies.update(r.cookies.get_dict())
    url = 'https://m.weibo.cn/api/comments/create'
    data = {'content': content, 'mid': mid, 'st': st}
    while True:
        try:
            r = requests.post(url, data=data, cookies=cookies, timeout=1)
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
            if mid != my_mid:
                mid_write_file(mid)
            com_suc_num += 1
            return True
        else:
            with lock:
                print('评论失败：' + detail_url)
                if r.json()['ok'] == 0:
                    print(r.json()['msg'])
                    errno = r.json()['errno']
                    # 频繁
                    if errno == '100005':
                        is_frequent = True
                    # 已经评论
                    elif errno == '20019':
                        mid_write_file(mid)
                    # 只允许粉丝评论
                    elif errno == '20210':
                        mid_write_file(mid)
                    # 发微博太多
                    elif errno == '20016':
                        exit()
                    # 异常
                    elif errno == '200002':
                        exit()
                    # 服务器走丢了
                    elif errno == '100001':
                        pass

            return False
    except SystemExit:
        import os
        # 退出进程
        os._exit(int(errno))
    except:
        with lock:
            print('评论失败：' + detail_url)
        if r.json()['errno'] == '100005':
            is_frequent = True
        return False


def edit_weibo(mid, content):
    """
    修改微博
    :param mid:
    :param content:
    :return:
    """
    global at_weibo
    print('正在修改微博')
    cookies = {'SUB': gsid}
    url = f'https://m.weibo.cn/detail/{mid}'
    r = requests.get(url, cookies=cookies)
    logging.info(str(r.status_code))
    st = r.cookies.get_dict()['XSRF-TOKEN']
    cookies.update(r.cookies.get_dict())
    url = f'https://m.weibo.cn/api/statuses/update'
    data = {'content': content, 'editId': mid, 'st': st}
    headers = {'Referer': 'https://m.weibo.cn'}
    r = requests.post(url, data=data, cookies=cookies, headers=headers)
    logging.info(str(r.status_code))
    if r.json()['ok'] == 1:
        print('修改微博成功')
    else:
        print(r.json()['msg'])
        at_weibo = False


def after_zero(t):
    """
    判断是否是当天零点后发布的
    :param t:
    :return:
    """
    if t >= int(time.time()) - int(time.time() - time.timezone) % 86400:
        return True
    return False


def write_file(file_name, text):
    """
    写入文件
    :param file_name:
    :param text:
    :return:
    """
    open(file_name, 'a').close()
    with open(file_name, 'r') as f:
        if text not in f.read():
            with open(file_name, 'a') as f1:
                f1.write(text + '\n')


def mid_write_file(mid):
    """
    记录已经评论的mid
    :param mid:
    :return:
    """
    write_file('mid.txt', mid)


def at_write_file(name):
    """
    记录已经at的name
    :param name:
    :return:
    """
    write_file('at.txt', name)


def in_file(file_name, text):
    """
    判断文本是否在文件里
    :param file_name:
    :param text:
    :return:
    """
    open(file_name, 'a').close()
    with open(file_name, 'r') as f:
        return text in f.read()


def mid_in_file(mid):
    """
    判断mid是否已经评论
    :param mid:
    :return:
    """
    return in_file('mid.txt', mid)


def following_in_file(uid):
    """
    用户是否在关注列表里
    :param uid:
    :return:
    """
    return in_file('following.txt', uid)


def fans_in_file(uid):
    """
    用户是否在粉丝列表里
    :param uid:
    :return:
    """
    return in_file('fans.txt', uid)


def at_in_file(at):
    """
    用户是否在粉丝列表里
    :param uid:
    :return:
    """
    return in_file('at.txt', at)


def clear_mid_file():
    """
    清除mid文件
    :return:
    """
    open('mid.txt', 'w').close()


def clear_at_file():
    """
    清除at文件
    :return:
    """
    open('at.txt', 'w').close()


def clear_log():
    """
    清除log文件
    :return:
    """
    open('weibo.log', 'w').close()


def get_file_num(file_name):
    """
    获取文件中字符串的数量
    :return:
    """
    count = 0
    open(file_name, 'a').close()
    with open(file_name, 'r') as f:
        for i in f.read().split('\n'):
            if i != '':
                count += 1
    return count


def get_mid_num():
    """
    获取已经评论的mid的数量
    :return:
    """
    return get_file_num('mid.txt')


def get_at_list():
    """
    获取at列表
    :return:
    """
    open('at.txt', 'a').close()
    with open('at.txt', 'r') as f:
        text = f.read()
    return ['@' + i for i in text.split('\n') if i != '']


def get_weibo_info(gsid):
    """
    获取已发微博的信息
    :param gsid:
    :return:
    """
    cookies = {'SUB': gsid}
    uid = get_uid(gsid)
    url = f'https://m.weibo.cn/profile/info?uid={uid}'
    r = requests.get(url, cookies=cookies)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code) + ':' + r.text)
    info = []
    for i, j in enumerate(r.json()['data']['statuses']):
        t = j['created_at']
        t = time.mktime(time.strptime(' '.join(t.split()[:4] + t.split()[-1:]), '%c'))
        mid = r.json()['data']['statuses'][i]['mid']
        title = r.json()['data']['statuses'][i]['raw_text'][:-2]
        info.append({'t': t, 'mid': mid, 'title': title})
    info.sort(key=lambda keys: keys['t'], reverse=True)
    return info


def get_my_name():
    url = f'https://m.weibo.cn/profile/info?uid={uid}'
    r = requests.get(url)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    return r.json()['data']['user']['screen_name']


def wait_time(n):
    """
    等待n秒
    :param n:
    :return:
    """
    while n + 1:
        time.sleep(1)
        sys.stdout.write(f'\r等待时间：{n}秒')
        n -= 1


def get_follow():
    def get_following_list():
        following_list = []
        page = 1
        cookies = {'SUB': gsid}
        while True:
            url = f'https://m.weibo.cn/api/container/getIndex?containerid=231093_-_selffollowed&page={page}'
            while True:
                try:
                    r = requests.get(url, cookies=cookies)
                    if r.status_code == 418:
                        raise
                    r.json()
                    break
                except:
                    wait_time(120)
            if r.json()['ok'] == 0:
                break
            card_page = 0
            if len(r.json()['data']['cards']) == 2:
                card_page = 1
            for i in r.json()['data']['cards'][card_page]['card_group']:
                screen_name = i['user']['screen_name']
                uid = i['user']['id']
                print(screen_name, uid)
                following_list.append(str(uid))
            print(len(following_list))
            page += 1
        return following_list

    def get_fans_list():
        fans_list = []
        cookies = {'SUB': gsid}
        since_id = ''
        while True:
            url = f'https://m.weibo.cn/api/container/getIndex?containerid=231016_-_selffans&since_id={since_id}'
            r = requests.get(url, cookies=cookies)
            if r.status_code == 418:
                wait_time(60)
            if r.json()['ok'] == 0:
                break
            card_page = 0
            if len(r.json()['data']['cards']) == 2:
                card_page = 1
            for i in r.json()['data']['cards'][card_page]['card_group']:
                screen_name = i['user']['screen_name']
                uid = i['user']['id']
                print(screen_name, uid)
                fans_list.append(str(uid))
            print(len(fans_list))
            if 'since_id' not in r.json()['data']['cardlistInfo']:
                break
            since_id = r.json()['data']['cardlistInfo']['since_id']
        return fans_list

    if comment_following:
        try:
            open('following.txt', 'r').close()
        except:
            print('正在爬取关注列表')
            with open('fans.txt', 'w') as f:
                f.write('\n'.join(get_following_list()))
    if comment_follow_me:
        try:
            open('fans.txt', 'r').close()
        except:
            print('正在爬取粉丝列表')
            with open('fans.txt', 'w') as f:
                f.write('\n'.join(get_fans_list()))


def at_weibo_gen():
    while True:
        name = yield
        if not at_in_file(name):
            at_write_file(name)
        at_list = get_at_list()
        if len(at_list) and len(at_list) % 50 == 0:
            content = weibo_title + ' ' + ' '.join(at_list)
            edit_weibo(my_mid, content)


at_gen = at_weibo_gen()
next(at_gen)


def get_mid(cid, page=1):
    """
    获取帖子
    :param cid: 超话id
    :param page: 页数
    :return: 帖子列表
    """
    global is_frequent

    def analysis_and_join_list(mblog):
        time_state = mblog['created_at']
        t = mblog['latest_update']
        t = time.mktime(time.strptime(' '.join(t.split()[:4] + t.split()[-1:]), '%c'))
        mid = mblog['mid']
        text = mblog['text']
        user_id = str(mblog['user']['id'])
        screen_name = mblog['user']['screen_name']
        if not after_zero(t):
            return
        if at_weibo:
            at_gen.send(screen_name)
        if at_comment and '@' + my_name in text:
            pass
        else:
            if comment_following and not following_in_file(user_id):
                return False
            if comment_follow_me and not fans_in_file(user_id):
                return False
        if mid != my_mid and not mid_in_file(mid) and user_id != uid:
            print(screen_name.strip().replace('\n', ''), time_state, mid, user_id)
            mid_list.append((mid, user_id, text, screen_name))
            return True
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
    get_mid_max_r = gen.send(get_mid_max)
    while i < page:
        length = len(mid_list)
        with lock:
            print('*' * 100)
            print('第%d页' % (p + 1))
        url = f'https://m.weibo.cn/api/container/getIndex?containerid={cid}_-_sort_time' + since_id
        wait_time = 0.5
        while True:
            try:
                if wait_time >= 8:
                    is_frequent = True
                    return mid_list[:get_mid_max_r]
                r = req.get(url)
                logging.info(str(r.status_code))
                if r.status_code == 200 and r.json()['ok'] == 1:
                    break
                # 反爬
                elif r.status_code == 418:
                    time.sleep(wait_time)
                elif r.status_code == 502:
                    time.sleep(0.5)
                wait_time *= 2
            except:
                pass
        card_page = 0
        try:
            if p + 1 >= start_page:
                # 判断是否是第一页
                if r.json()['data']['cards'][0]['card_group'][0]['card_type'] == '121':
                    card_page = 1
                    mblog = r.json()['data']['cards'][0]['card_group'][1]['mblog']
                    if analysis_and_join_list(mblog) is None:
                        return mid_list[:get_mid_max_r]
                card_group = r.json()['data']['cards'][card_page]['card_group']
                for j in card_group:
                    mblog = j['mblog']
                    if analysis_and_join_list(mblog) is None:
                        return mid_list[:get_mid_max_r]
            since_id = '&since_id=' + str(r.json()['data']['pageInfo']['since_id'])
        except:
            logging.error(r.json())
            traceback.print_exc()
            return mid_list[:get_mid_max_r]
        if length < len(mid_list):
            i += 1
        p += 1
        if p >= get_page_max:
            break
        if len(mid_list) >= get_mid_max_r:
            break
    return mid_list[:get_mid_max_r]


def get_my_mid():
    """
    获取配置中自己的帖子
    :return:
    """
    mid = cf.GetStr('配置', 'mid')
    if mid == '':
        for info in get_weibo_info(gsid):
            mid = info['mid']
            title = info['title']
            if title == weibo_title:
                cf.Add('配置', 'mid', mid)
                return mid
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


def is_today(t=None):
    """
    获取配置中的信息的时间
    :return: bool
    """
    if t is None:
        t = cf.GetFloat('配置', 'time')
    zero_time = int(time.time()) - int(time.time() - time.timezone) % 86400
    if t != None and t >= zero_time:
        return True
    else:
        return False


def wait_zero():
    """
    等待零点
    :return:
    """
    t1 = 0
    while True:
        t = int(time.time() - time.timezone) % 86400
        sys.stdout.write(f'\r距离零点：{str(86400 - t)}s')
        if t1 > t:
            print()
            break
        else:
            t1 = t
        time.sleep(0.1)


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
    logging.info(str(r.status_code))
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
    每日vip签到成长值+1
    :param gsid:
    :return:
    """
    url = 'https://new.vip.weibo.cn/aj/task/qiandao?task_id=1&F=growth_yhzx_didao'
    cookies = {'SUB': gsid}
    headers = {
        'Referer': 'https://new.vip.weibo.cn'}
    req = requests.Session()
    r = req.get(url, headers=headers, cookies=cookies)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    print(r.json()['msg'])


def vip_pk(gsid):
    """
    每日vip pk成长值+1
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


def vip_task_complete(gsid):
    """
    vip完成今日所有任务,成长值+2
    :return:
    """
    url = 'https://new.vip.weibo.cn/aj/task/addscore'
    cookies = {'SUB': gsid}
    r = requests.get(url, cookies=cookies)
    try:
        print(r.json()['msg'])
    except:
        pass


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
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    if r.json()['code'] == 100000:
        return True
    return False


def init_log(level):
    """
    初始化log
    :param level:
    :return:
    """
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(pathname)s->%(funcName)s line %(lineno)d : %(message)s"
    DATE_FORMAT = "%m/%d/%Y %H:%M:%S %p"
    logging.basicConfig(handlers=[logging.FileHandler('weibo.log', 'a', 'utf-8')], level=level, format=LOG_FORMAT,
                        datefmt=DATE_FORMAT)


def random_gen(random_list):
    """
    随机生成器
    :param random_list:
    :return:
    """
    while True:
        yield random.choice(random_list)


def next_gen():
    """
    判断生成器并返回下一个
    :return:
    """
    import types
    obj = None
    while True:
        if type(obj) is types.GeneratorType:
            obj = yield next(obj)
        else:
            obj = yield obj


gen = next_gen()
next(gen)


def start_comments():
    """
    开始评论
    :return:
    """
    global com_suc_num
    global is_frequent
    mid_list = get_mid(cid, get_mid_page)
    mid_lists = []
    for mid, user_id, text, name in mid_list:
        while True:
            content = gen.send(default_content)
            for key in keywords_comment.keys():
                if key in text:
                    content = gen.send(keywords_comment[key])
            if user_id in user_comments.keys():
                content = gen.send(user_comments[user_id])
            if len(content) <= 140:
                break
            mid_lists.append((mid, content.format(mid=my_mid, uid=uid, name=name)))
    com_suc_num = 0
    print('开始评论')
    try:
        pool.map(comment, mid_lists)
    except:
        is_frequent = True
    print('评论成功数：' + str(com_suc_num))
    print('总评论数：' + str(get_mid_num()))
    push_wechat('weibo_comments', f'''
                {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
                评论成功数：{com_suc_num}  总评论数：{get_mid_num()}''')


def loop_comments(num):
    """
    循环评论
    :param num:
    :return:
    """
    global uid
    global is_frequent
    global my_name
    for i in range(num):
        get_uid(gsid)
        if get_mid_num() >= comment_max:
            print(f'你已经评论{comment_max}条了')
        if is_frequent:
            n = frequent_wait_time
            push_wechat('weibo_comments', f'''
                        {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
                        请求过于频繁,正在等待{n}秒''')
            wait_time(n)
            print()
            is_frequent = False
        else:
            n = comments_wait_time
        wait_time(n)
        my_name = get_my_name()
        sys.stdout.write(f'\r第{i + 1}次，开始获取微博\n')
        push_wechat('weibo_comments', f'''
            {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
            第{i + 1}次，开始获取微博''')
        start_comments()
    clear_at_file()


if __name__ == '__main__':
    # wait_zero()  # 等待零点执行
    comment_following = True  # 是否只评论已关注的
    comment_follow_me = False  # 是否只评论关注自己的
    at_weibo = True  # @超话里的人到自己微博
    at_comment = True  # 是否评论@自己的
    get_mid_page = 200  # 一次爬微博页数
    get_page_max = 200  # 爬取失败时最多爬取的页数
    get_mid_max = random_gen(range(50, 60))  # 一次最多评论微博数量
    comment_max = 2000  # 最多评论次数
    loop_comments_num = 20  # 运行次数
    comments_wait_time = 1  # 每次延迟运行时间
    frequent_wait_time = 600  # 频繁等待时间

    # 微信推送 http://sc.ftqq.com
    SCKEY = ''

    # 评论的超话
    st_name = '橘子工厂'

    # 发送微博的标题
    weibo_title = f'#{st_name}[超话]#积分！'

    # 需要发送的群聊的id
    gid_list = [

    ]

    # 微博链接
    # {uid}和{mid}会自动替换
    mid_link = 'https://m.weibo.cn/{uid}/{mid}'

    # 随机评论列表
    random_list = [
        '@{name} ' + mid_link
    ]

    # 随机评论
    # 构造生成器：生成器 = random_gen(随机列表)
    # 需要赋值才能生效
    # 例：default_content = random_comment
    # 例：user_comments = {'xxx': random_comment}
    random_comment = random_gen(random_list)

    # 自定义用户评论
    user_comments = {
        # 用户id:评论内容
    }

    # 自定义关键字评论
    keywords_comment = {
        # 关键字:评论内容
        # '异常': random_comment,
        # '勿带链接': 'xxx'
    }

    # 带上链接
    random_comment = random_gen(list(map(lambda i: i + ' ' + mid_link, random_list)))
    # 默认评论内容
    default_content = random_comment

    init_log(logging.INFO)
    gsid = get_gsid()
    uid = get_uid(gsid)
    cid = find_super_topic(st_name)
    get_follow()
    if is_today():
        print('正在读取微博')
        my_mid = get_my_mid()
        if not my_mid:
            print('读取失败')
            exit()
        else:
            print('读取成功')
    else:
        clear_log()
        clear_at_file()
        clear_mid_file()
        print('正在创建微博')
        my_mid = create_weibo(gen.send(weibo_title), cid)
        if my_mid == False:
            print('创建失败')
            exit()
        else:
            print('创建成功')
            # 发送微博到群组
            for gid in gid_list:
                group_chat_comments(gid)
        print('*' * 100)
        print('获取每日vip签到成长值')
        vip_sign(gsid)
        print('*' * 100)
        print('获取vip pk成长值')
        vip_pk(gsid)
        print('*' * 100)
        print('获取超话登录积分')
        login_integral(gsid)
        print('*' * 100)
        print('获取每日签到积分')
        sign_integral(gsid)
        print('*' * 100)
        print('获取完成所有vip任务成长值')
        vip_task_complete(gsid)
        print('*' * 100)
    print('https://m.weibo.cn/detail/' + my_mid)
    loop_comments(loop_comments_num)
