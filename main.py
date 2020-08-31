import contextlib
import hashlib
import json
import logging
import random
import re
import sys
import time
import os
from multiprocessing.dummy import Pool
from threading import Lock, Thread
import requests
from bs4 import BeautifulSoup
from config import Config

lock = Lock()
pool = Pool(100)
is_frequent = False
is_too_many_weibo = False
writable = True
is_finish = False
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/74.0'}
cf = Config('config.ini', '配置')


def create_weibo(text, cid):
    """
    创建微博
    :param text: 内容
    :param cid: 超话id
    :return:
    """

    def retry():
        for info in get_weibo_info(gsid):
            t = info['t']
            mid = info['mid']
            title = info['title']
            if title == weibo_title and t > time.time() - get_time_after_zero() or abs(
                    t - get_close_zero_time()) < 600:
                add_config(mid)
                return mid
        else:
            print('创建微博失败,正在重试')
            time.sleep(1)
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
    code = r.json()['code']
    if code == 100000:
        mid = r.json()['data']['mid']
        add_config(mid)
        return mid
    elif code == 100001:
        return False
    elif code == 20019:
        return retry()
    # Redis连接异常
    elif code == 200124:
        return retry()
    else:
        print(r.json()['msg'])
        return retry()


def add_config(mid):
    cf.Add('配置', 'mid', mid)
    cf.Add('配置', 'time', str(time.time()))


def comment(args):
    """
    评论微博
    :param args:
    :return:
    """
    global com_suc_num
    global com_err_num
    global is_frequent
    global is_too_many_weibo
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
                com_err_num += 1
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
                logging.info(str(r.status_code) + ':' + mid + ':' + str(r.json()))
            except:
                logging.warning(str(r.status_code) + ':' + mid)
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
                com_err_num += 1
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
                        mid_error_write_file(mid)
                    # 只允许关注用户评论
                    elif errno == '20206':
                        mid_error_write_file(mid)
                    # 发微博太多
                    elif errno == '20016':
                        is_too_many_weibo = True
                    # 异常
                    elif errno == '200002':
                        exit()
                    # 服务器走丢了
                    elif errno == '100001':
                        mid_error_write_file(mid)
                    # 在黑名单中，无法进行评论
                    elif errno == '20205':
                        mid_error_write_file(mid)
                    # 微博不存在或暂无查看权限
                    elif errno == '20101':
                        mid_error_write_file(mid)
                    # 由于作者隐私设置，你没有权限评论此微博
                    elif errno == '20130':
                        mid_error_write_file(mid)
            return False
    except SystemExit:
        # 退出进程
        push_wechat('weibo_comments', f'''{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}  
{errno}:{r.json()['msg']}''')
        os._exit(int(errno))
    except:
        with lock:
            print('评论失败：' + detail_url)
        if r.json()['errno'] == '100005':
            is_frequent = True
        com_err_num += 1
        return False


def edit_weibo(mid, content):
    """
    修改微博
    :param mid:
    :param content:
    :return:
    """
    global at_file
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
        at_file = False


def after_zero(t):
    """
    判断是否是当天零点后发布的
    :param t:
    :return:
    """
    if type(t) is str:
        if t == '刚刚':
            return True
        elif re.match('^(\d{1,2})分钟前$', t):
            if int(t[:-3]) * 60 < int(time.time() - time.timezone) % 86400:
                return True
        elif re.match('^(\d{1,2})小时前$', t):
            if int(t[:-3]) * 3600 < int(time.time() - time.timezone) % 86400:
                return True
        return False
    else:
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


def mid_error_write_file(mid):
    """
    记录评论失败的mid
    :param mid:
    :return:
    """
    write_file('mid_error.txt', mid)


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


def mid_error_in_file(mid):
    """
    是否是评论失败的mid
    :param mid:
    :return:
    """
    return in_file('mid_error.txt', mid)


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


def clear_mid_error_file():
    """
    清除mid_error文件
    :return:
    """
    open('mid_error.txt', 'w').close()


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


def clear_mid_json():
    """
    清除mid.json文件
    :return:
    """
    open('mid.json', 'w').close()


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


def get_mid_error_num():
    """
    获取无法评论数的mid的数量
    :return:
    """
    return get_file_num('mid_error.txt')


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
        try:
            t = j['created_at']
            t = time.mktime(time.strptime(' '.join(t.split()[:4] + t.split()[-1:]), '%c'))
            mid = r.json()['data']['statuses'][i]['mid']
        except:
            continue
        try:
            title = r.json()['data']['statuses'][i]['raw_text'][:-2]
        except:
            title = r.json()['data']['statuses'][i]['text']
        info.append({'t': t, 'mid': mid, 'title': title})
    info.sort(key=lambda keys: keys['t'], reverse=True)
    return info


def get_my_name():
    """
    获取自己的名字
    :return:
    """
    name = cf.GetStr('配置', 'name')
    if name != '':
        return name
    url = f'https://m.weibo.cn/profile/info?uid={uid}'
    r = requests.get(url)
    try:
        logging.info(str(r.status_code) + ':' + str(r.json()))
    except:
        logging.warning(str(r.status_code))
    name = r.json()['data']['user']['screen_name']
    cf.Add('配置', 'name', name)
    return name


def wait_time(n, text='等待时间'):
    """
    等待n秒
    :param n:
    :return:
    """
    while n + 1:
        time.sleep(1)
        with lock:
            w_gen.send({text: n})
        n -= 1
    with lock:
        w_gen.send({text: None})


def get_follow():
    """
    获取粉丝和关注列表
    :return:
    """

    def get_following_list():
        """
        获取关注列表
        :return:
        """
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
        """
        获取粉丝列表
        :return:
        """
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
    """
    at生成器
    :return:
    """
    while True:
        name = yield
        if not at_in_file(name):
            at_write_file(name)
        at_list = get_at_list()
        if len(at_list) and len(at_list) % 50 == 0:
            content = weibo_title + ' ' + ' '.join(at_list)
            if at_edit_weibo:
                edit_weibo(my_mid, content)


at_gen = at_weibo_gen()
next(at_gen)


def write_gen():
    """
    生成器并行输出
    :return:
    """
    l = {}
    while True:
        d = yield
        if type(d) is dict:
            l[list(d)[0]] = d[list(d)[0]]
            s = '\r' + ','.join([str(i) + ':' + str(l[i]) for i in l if l[i] != None])
            if writable:
                sys.stdout.write(s + ' ' * 32)
                sys.stdout.flush()


w_gen = write_gen()
next(w_gen)


def get_mid(cid):
    """
    获取微博
    :param cid: 超话id
    :param page: 页数
    :return: 微博列表
    """
    global is_frequent

    def mid_in_file(mid):
        return len([i for i in read_mid() if 'mid' in i.keys() and mid == i['mid']]) == 1

    def analysis_and_join_list(mblog):
        global is_finish
        time_state = mblog['created_at']
        try:
            t = mblog['latest_update']
            t = time.mktime(time.strptime(' '.join(t.split()[:4] + t.split()[-1:]), '%c'))
        except:
            t = time_state
        mid = mblog['mid']
        text = mblog['text']
        user_id = str(mblog['user']['id'])
        screen_name = mblog['user']['screen_name']
        if not after_zero(t):
            is_finish = True
            return
        if is_finish and mid_in_file(mid):
            return
        write_mid({'mid': mid, 'user_id': user_id, 'text': text, 'screen_name': screen_name})
        return True

    since_id = ''
    req = requests.Session()
    req.headers = headers
    i = 1
    while True:
        with lock:
            w_gen.send({'正在爬取页数': i})
        url = f'https://m.weibo.cn/api/container/getIndex?containerid={cid}_-_sort_time' + since_id
        wait_time = 0.5
        while True:
            try:
                if wait_time >= 8:
                    is_frequent = True
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
            # 判断是否是第一页
            if r.json()['data']['cards'][0]['card_group'][0]['card_type'] == '121':
                card_page = 1
                mblog = r.json()['data']['cards'][0]['card_group'][1]['mblog']
                if analysis_and_join_list(mblog) is None:
                    with lock:
                        w_gen.send({'正在爬取页数': None})
                    return
            card_group = r.json()['data']['cards'][card_page]['card_group']
            for j in card_group:
                mblog = j['mblog']
                if analysis_and_join_list(mblog) is None:
                    with lock:
                        w_gen.send({'正在爬取页数': None})
                    return
            since_id = '&since_id=' + str(r.json()['data']['pageInfo']['since_id'])
        except:
            pass
        with lock:
            w_gen.send({'等待评论数': len(get_mid_list())})
        i += 1


def loop_get_mid(cid):
    """
    循环爬取mid
    :param cid:
    :return:
    """
    while True:
        with lock:
            w_gen.send({'等待评论数': len(get_mid_list())})
            t = gen.send(get_weibo_time)
        wait_time(t, '获取微博等待时间')
        get_mid(cid)


def write_mid(mid_dict: dict):
    """
    把mid写入文件
    :param mid_dict:
    :return:
    """
    open('mid.json', 'a').close()
    with open('mid.json', 'r') as f1:
        try:
            l = [dict(t) for t in set([tuple(d.items()) for d in json.loads(f1.read())])]
        except:
            l = []
    with open('mid.json', 'w+') as f:
        if mid_dict not in l:
            l.append(mid_dict)
        f.write(json.dumps(l, indent=2))


def read_mid():
    """
    读取mid列表文件
    :return:
    """
    open('mid.json', 'a').close()
    with open('mid.json', 'r') as f1:
        try:
            l = json.loads(f1.read())
        except:
            l = []
    return l


def get_mid_list():
    """
    获取未评论的mid列表
    :return:
    """
    mid_list = []
    for mid_dict in read_mid():
        comments = True
        screen_name = mid_dict['screen_name']
        text = mid_dict['text']
        user_id = mid_dict['user_id']
        mid = mid_dict['mid']
        if at_file:
            at_gen.send(screen_name)
        if at_comment and '@' + my_name in text:
            pass
        else:
            if comment_following and not following_in_file(user_id):
                comments = False
            if comment_follow_me and not fans_in_file(user_id):
                comments = False
        if comments and mid != my_mid and not mid_in_file(mid) and not mid_error_in_file(mid) and user_id != uid:
            mid_list.append((mid, user_id, text, screen_name))
    return mid_list


def get_my_mid():
    """
    获取配置中自己的微博
    :return:
    """
    mid = cf.GetStr('配置', 'mid')
    if mid == '':
        info_list = get_weibo_info(gsid)
        if not info_list:
            return False
        for info in info_list:
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


def get_time_after_zero():
    """
    获取零点后的秒数
    :return:
    """
    return int(time.time() - time.timezone) % 86400


def wait_zero():
    """
    等待零点
    :return:
    """
    while True:
        t = get_time_after_zero()
        if t == 0:
            with lock:
                w_gen.send({'距离零点': None})
            break
        with lock:
            w_gen.send({'距离零点': f'{86400 - t}s'})
        time.sleep(0.1)


def get_uid(gsid, config=False):
    """
    获取用户的id
    :param gsid:
    :return:
    """
    global is_frequent
    if config:
        uid = cf.GetStr('配置', 'uid')
        if uid != '':
            return uid
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
        uid = r.json()['data']['uid']
        if not cf.GetStr('配置', uid):
            cf.Add('配置', 'uid', uid)
        return uid
    except:
        if not r.json()['data']['login']:
            print('请重新登录')
            push_wechat('weibo_comments', '请重新登录')
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
    获取微博的bid
    bid链接群聊不会被转换成短链
    :param mid: 微博id
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


@contextlib.contextmanager
def unwritable():
    """
    控制输出的上下文管理器
    :return:
    """
    global writable
    with lock:
        writable = False
    yield
    with lock:
        writable = True


def retry(n, t):
    """
    重试装饰器
    :param n: 重试次数
    :param t: 重试时间
    :return:
    """

    def wrapper(f):
        def retry_thread(f, *args, **kwargs):
            for i in range(n):
                try:
                    with unwritable():
                        r = f(*args, **kwargs)
                except:
                    r = False
                    logging.warning(str(sys.exc_info()))
                if r == False:
                    time.sleep(t)
                else:
                    break

        def wrapped(*args, **kwargs):
            Thread(target=lambda: retry_thread(f, *args, **kwargs)).start()

        return wrapped

    return wrapper


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
    try:
        print(r.json()['msg'])
    except:
        pass


@retry(3, 1)
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


@retry(3, 1)
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


@retry(100, 10)
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
    if r.json()['code'] == 100000 and not r.json()['toast']:
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


def get_close_zero_time():
    """
    获取最靠近的零点时间戳
    :return:
    """
    if get_time_after_zero() > 86400 / 2:
        return time.time() - get_time_after_zero() + 86400
    else:
        return time.time() - get_time_after_zero()


def zero_handle(run=False):
    """
    零点执行
    :param run:
    :return:
    """
    global my_mid
    global is_too_many_weibo
    while True:
        while not run and get_time_after_zero() != 0:
            time.sleep(0.5)
        if run:
            info_list = get_weibo_info(gsid)
            if info_list:
                for info in info_list:
                    t = info['t']
                    mid = info['mid']
                    title = info['title']
                    if title == weibo_title and t > time.time() - get_time_after_zero() or abs(
                            t - get_close_zero_time()) < 600:
                        my_mid = mid
                        add_config(my_mid)
                        return
        clear_log()
        if at_file:
            clear_at_file()
        clear_mid_file()
        clear_mid_error_file()
        clear_mid_json()
        with unwritable():
            if not run:
                print()
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + '|正在创建微博')
            with lock:
                mid = create_weibo(gen.send(weibo_title), cid)
            if mid == False:
                print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + '|创建失败')
                push_wechat('weibo_comments', f'''  
                {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}   
************************  
创建微博失败  
************************''')
                is_too_many_weibo = True
                if 'my_mid' not in dir():
                    my_mid = get_my_mid()
                break
            else:
                my_mid = mid
                print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + '|创建成功')
                push_wechat('weibo_comments', f'''  
                {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}  
************************  
创建微博成功  
微博：https://m.weibo.cn/{uid}/{my_mid}  
************************''')
                print('https://m.weibo.cn/detail/' + my_mid)
                # 发送微博到群组
                for gid in gid_list:
                    try:
                        group_chat_comments(gid)
                    except:
                        logging.error(str(sys.exc_info()))
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
            if run:
                break


def start_comments(i):
    """
    开始评论
    :return:
    """
    global com_suc_num
    global com_err_num
    global is_frequent
    global commentable
    with lock:
        get_mid_max_r = gen.send(get_mid_max)
    while True:
        mid_list = get_mid_list()
        if not mid_list:
            pass
        else:
            if (86400 - last_comment_for_zero_time) < get_time_after_zero():
                break
            elif commentable:
                commentable = False
                break
            with lock:
                if len(mid_list) >= gen.send(start_comment_num):
                    break
        time.sleep(1)
    mid_lists = []
    for mid, user_id, text, name in mid_list[:get_mid_max_r]:
        n = 0
        while True:
            with lock:
                content = gen.send(default_content)
                for key in keywords_comment.keys():
                    if key in text:
                        content = gen.send(keywords_comment[key])
                if user_id in user_comments.keys():
                    content = gen.send(user_comments[user_id])
            content = content.format(my_mid=my_mid, my_uid=uid, my_name=my_name, name=name, mid=mid, uid=user_id)
            if len(content) <= 140:
                break
            else:
                if n > 3:
                    break
                n += 1
        mid_lists.append((mid, content))
    com_suc_num = 0
    com_err_num = 0
    with unwritable():
        print(f'\n{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}|第{i + 1}次评论')
        try:
            pool.map(comment, mid_lists)
        except:
            is_frequent = True
        print('当前时间：' + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        print('已爬取微博数：' + str(len(read_mid())))
        print('评论成功数：' + str(com_suc_num))
        print('评论失败数：' + str(com_err_num))
        print('总评论数：' + str(get_mid_num()))
        print('无法评论数：' + str(get_mid_error_num()))
    wait_comment_num = len(get_mid_list())
    with lock:
        w_gen.send({'等待评论数': wait_comment_num})
    push_wechat('weibo_comments', f'''  
{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}
************************
用户名：{my_name}  
微博：https://m.weibo.cn/{uid}/{my_mid}  
已爬取微博数：{len(read_mid())}  
************************
第{i + 1}次评论  
评论成功数：{com_suc_num}  
评论失败数：{com_err_num}  
总评论数：{get_mid_num()}  
无法评论数：{get_mid_error_num()}  
待评论数：{wait_comment_num}''')
    if (86400 - last_comment_for_zero_time) < get_time_after_zero():
        wait_zero()


def loop_comments(num):
    """
    循环评论
    :param num:
    :return:
    """
    global uid
    global is_frequent
    global is_too_many_weibo
    global my_name
    for i in range(num):
        get_uid(gsid)
        with lock:
            w_gen.send({'等待评论数': len(get_mid_list())})
        while is_too_many_weibo:
            wait_time(too_many_weibo_wait_time, '发微博太多等待时间')
            is_too_many_weibo = False
            if not is_today():
                zero_handle(True)
        else:
            if get_mid_num() >= comment_max:
                print(f'你今天已经评论{comment_max}条了')
                wait_zero()
            while True:
                if is_frequent:
                    push_wechat('weibo_comments', f'''{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}  
    请求过于频繁,正在等待{frequent_wait_time}秒''')
                    wait_time(frequent_wait_time, '频繁等待时间')
                    print()
                    is_frequent = False
                else:
                    wait_time(loop_comments_time, '评论等待时间')
                    break
                get_uid(gsid)
            start_comments(i)
    if at_file:
        clear_at_file()


if __name__ == '__main__':
    # wait_zero()  # 等待零点执行
    comment_following = False  # 是否只评论已关注的
    comment_follow_me = False  # 是否只评论关注自己的
    at_comment = False  # 是否评论@自己的，检测微博标题是否@自己，只适用于上面两条过滤条件后生效
    at_file = False  # 爬取超话里的用户名保存到文件
    at_edit_weibo = False  # 自动在微博标题上at超话里的用户，要先开at_file
    get_mid_max = random_gen(range(50, 60))  # 一次最多评论微博数量
    get_weibo_time = random_gen(range(10, 20))  # 获取微博等待时间
    start_comment_num = random_gen(range(50, 60))  # 开始评论的评论数量
    last_comment_for_zero_time = 600  # 距离0点前开始今天最后一次评论的时间，23:50分最后一次评论
    comment_max = 2000  # 一天最多评论次数，超过后等待零点继续
    loop_comments_num = 99999  # 循环运行次数
    loop_comments_time = 10  # 每次循环等待时间
    frequent_wait_time = 600  # 频繁等待时间
    too_many_weibo_wait_time = 3600 * 6  # 发微博太多等待时间

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
    # 括号里的会自动替换
    # my_uid：自己的uid，my_mid：自己的mid，my_name：自己的名字
    # uid：当前要评论的微博的用户的uid，mid：当前要评论的微博的mid，name：要评论的微博的用户的名字
    mid_link = 'https://m.weibo.cn/{my_uid}/{my_mid}'

    # 随机评论列表
    random_list = [
        '@{name}'
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
        '异常': random_comment,
        '勿带链接': random_comment,
        '别带链接': random_comment
    }

    # 带上链接
    random_comment = random_gen(list(map(lambda i: i + ' ' + mid_link, random_list)))
    # 默认评论内容
    default_content = random_comment

    init_log(logging.INFO)
    gsid = get_gsid()
    uid = get_uid(gsid, True)
    while uid is None:
        wait_time(600)
        uid = get_uid(gsid)
    is_frequent = False
    my_name = get_my_name()
    cid = find_super_topic(st_name)
    get_follow()
    if is_today():
        print('正在读取微博')
        my_mid = get_my_mid()
        if not my_mid:
            print('读取失败')
            exit()
    else:
        zero_handle(True)
    print('读取成功')
    print('https://m.weibo.cn/detail/' + my_mid)
    t_loop_get_mid = Thread(target=loop_get_mid, args=(cid,))
    t_loop_get_mid.setDaemon(True)
    t_loop_get_mid.start()
    t_loop_zero_handle = Thread(target=zero_handle)
    t_loop_zero_handle.setDaemon(True)
    t_loop_zero_handle.start()
    t_loop_comments = Thread(target=loop_comments, args=(loop_comments_num,))
    t_loop_comments.start()
    commentable = False
    while True:
        try:
            command = input()
        except KeyboardInterrupt:
            os._exit(0)
        # 立即评论
        if command == '':
            commentable = True
        # 不爬到底
        elif command == ' ':
            is_finish = True
        # 退出
        elif command == 'exit':
            os._exit(0)
