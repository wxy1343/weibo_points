* [简介](#简介)
* [功能](#功能)
* [流程图](#流程图)
* [安装](#安装)
  * [1.下载脚本](#1下载脚本)
  * [2.安装依赖](#2安装依赖)
* [使用](#使用)
  * [1.运行脚本](#1运行脚本)
  * [2.获取gsid](#2获取gsid)
# 简介
这是一个微博超话自动获取积分的工具，每天获取积分特别麻烦，所以写了这个代码来自动完成
# 功能
* 发送积分贴到超话
* 自动评论积分贴(可以带链接)
* 自动vip 签到 and pk
* 连续访问积分
* 超话登录积分
# 流程图
![流程图]()
# 安装
## 1.下载脚本
```bash
$ git clone https://github.com/1343890272/weibo_comments
```
## 2.安装依赖
```bash
$ pip install -r requirements.txt
```
# 使用
## 1.运行脚本
```bash
$ python main.py
```
## 2.获取gsid
1.用Chrome打开<https://m.weibo.cn/login>  
2.登录成功后，按F12键打开Chrome开发者工具
3.点击Chrome开发者工具中的Network->Name中的m.weibo.cn->Headers->Request Headers->cookie->SUB等于号后面到封号的值就是gsid
![gsid](https://github.com/1343890272/weibo_comments/blob/master/gsid.png)
