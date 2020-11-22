from flask import Flask,render_template,request
import sys
import requests
import json
import yaml
import oss2
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from urllib3.exceptions import InsecureRequestWarning

app = Flask(__name__)

# 读取yml配置
def getYmlConfig(yaml_file='config.yml'):
    file = open(yaml_file, 'r', encoding="utf-8")
    file_data = file.read()
    file.close()
    config = yaml.load(file_data, Loader=yaml.FullLoader)
    return dict(config)


# 全局配置
config = getYmlConfig(yaml_file='config.yml')

def getSession(username,password):
    params = {
        'login_url': 'http://authserver.cumt.edu.cn/authserver/login?service=http%3A%2F%2Fauthserver.cumt.edu.cn%2Fauthserver%2Fmobile%2Fcallback%3FappId%3D744946645598208000',
        # 保证学工号和密码正确下面两项就不需要配置
        'needcaptcha_url': '',
        'captcha_url': '',
        'username': username,
        'password': password
    }

    cookies = {}
    # 借助上一个项目开放出来的登陆API，模拟登陆
    api= "http://47.98.49.243:8080/wisedu-unified-login-api-v1.0/api/login"
    res = requests.post(api, params)
    cookieStr = str(res.json()['cookies'])
    if cookieStr == 'None':
        print(res.json())
        return None

    # 解析cookie
    for line in cookieStr.split(';'):
        name, value = line.strip().split('=', 1)
        cookies[name] = value

    # print(cookies)
    session = requests.session()
    session.cookies = requests.utils.cookiejar_from_dict(cookies)
    session.get(url='https://cumt.campusphere.net/portal/login')
    return session
# 查询表单
def queryForm(session):
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 4.4.4; OPPO R11 Plus Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Safari/537.36 yiban/8.1.11 cpdaily/8.1.11 wisedu/8.1.11',
        'content-type': 'application/json',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Language': 'zh-CN,en-US;q=0.8',
        'Content-Type': 'application/json;charset=UTF-8'
    }
    queryCollectWidUrl = 'https://cumt.campusphere.net/wec-counselor-collector-apps/stu/collector/queryCollectorProcessingList'
    params = {
        'pageSize': 6,
        'pageNumber': 1
    }
    res = session.post(queryCollectWidUrl, headers=headers,
                       data=json.dumps(params))
    if len(res.json()['datas']['rows']) < 1:
        return None
    for i in range(0,4,1):
            title = res.json()['datas']['rows'][i]['subject']
            # print(title)
            if "日报告" in title:
                collectWid = res.json()['datas']['rows'][0]['wid']
                formWid = res.json()['datas']['rows'][0]['formWid']

                detailCollector = 'https://cumt.campusphere.net/wec-counselor-collector-apps/stu/collector/detailCollector'
                res = session.post(url=detailCollector, headers=headers,
                                data=json.dumps({"collectorWid": collectWid}))
                schoolTaskWid = res.json()['datas']['collector']['schoolTaskWid']

                getFormFields = 'https://cumt.campusphere.net/wec-counselor-collector-apps/stu/collector/getFormFields'
                res = session.post(url=getFormFields, headers=headers, data=json.dumps(
                    {"pageSize": 100, "pageNumber": 1, "formWid": formWid, "collectorWid": collectWid}))

                form = res.json()['datas']['rows']
                return {'collectWid': collectWid, 'formWid': formWid, 'schoolTaskWid': schoolTaskWid, 'form': form}
            else:
                pass

# 填写form
def fillForm(session, form):
    sort = 1
    for formItem in form[:]:
        # 只处理必填项
        if formItem['isRequired'] == 1:
            default = config['cpdaily']['defaults'][sort - 1]['default']
            if formItem['title'] != default['title']:
                print('第%d个默认配置不正确，请检查' % sort)
                exit(-1)
            # 文本直接赋值
            if formItem['fieldType'] == 1 or formItem['fieldType'] == 5:
                formItem['value'] = default['value']
            # 单选框需要删掉多余的选项
            if formItem['fieldType'] == 2:
                # 填充默认值
                formItem['value'] = default['value']
                fieldItems = formItem['fieldItems']
                for i in range(0, len(fieldItems))[::-1]:
                    if fieldItems[i]['content'] != default['value']:
                        del fieldItems[i]
            # 多选需要分割默认选项值，并且删掉无用的其他选项
            if formItem['fieldType'] == 3:
                fieldItems = formItem['fieldItems']
                defaultValues = default['value'].split(',')
                for i in range(0, len(fieldItems))[::-1]:
                    flag = True
                    for j in range(0, len(defaultValues))[::-1]:
                        if fieldItems[i]['content'] == defaultValues[j]:
                            # 填充默认值
                            formItem['value'] += defaultValues[j] + ' '
                            flag = False
                    if flag:
                        del fieldItems[i]
            sort += 1
        else:
            form.remove(formItem)
    return form

# 提交表单
def submitForm(formWid, collectWid, schoolTaskWid, form, session):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 4.4.4; OPPO R11 Plus Build/KTU84P) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/33.0.0.0 Safari/537.36 okhttp/3.12.4',
        'CpdailyStandAlone': '0',
        'extension': '1',
        'Cpdaily-Extension': '1wAXD2TvR72sQ8u+0Dw8Dr1Qo1jhbem8Nr+LOE6xdiqxKKuj5sXbDTrOWcaf v1X35UtZdUfxokyuIKD4mPPw5LwwsQXbVZ0Q+sXnuKEpPOtk2KDzQoQ89KVs gslxPICKmyfvEpl58eloAZSZpaLc3ifgciGw+PIdB6vOsm2H6KSbwD8FpjY3 3Tprn2s5jeHOp/3GcSdmiFLYwYXjBt7pwgd/ERR3HiBfCgGGTclquQz+tgjJ PdnDjA==',
        'Content-Type': 'application/json; charset=utf-8',
        # 请注意这个应该和配置文件中的host保持一致
        'Host': 'cumt.campusphere.net',
        'Connection': 'Keep-Alive',
        'Accept-Encoding': 'gzip'
    }

    # 默认正常的提交参数json
    params = {"formWid": formWid, "address": "江苏省徐州市铜山区行健西路", "collectWid": collectWid, "schoolTaskWid": schoolTaskWid,
              "form": form}
    # print(params)
    submitForm = 'https://cumt.campusphere.net/wec-counselor-collector-apps/stu/collector/submitForm'
    r = session.post(url=submitForm, headers=headers,
                     data=json.dumps(params))
    msg = r.json()['message']
    return msg

@app.route('/submit/<username>/<password>', methods=['POST'])
def tst(username,password):
    session = getSession(str(username),str(password))
    if session != None:
        # return  "模拟登陆成功"
        params = queryForm(session)
        if str(params) == 'None':
            return "获取最新待填写问卷失败，可能是辅导员还没有发布"
            # exit(-1)
        form = fillForm(session, params['form'])
        # return "填写问卷成功"
        msg = submitForm(params['formWid'], params['collectWid'],
                            params['schoolTaskWid'], form, session)
        if msg == 'SUCCESS':
            return "自动提交成功"
        elif msg == '该收集已填写无需再次填写':
            return "今日已提交"
        else:
            return "自动提交失败" + msg
            #exit(-1)
    else:
        return "模拟登陆失败"
        #exit(-1)

if __name__ == '__main__':
    # Flask
    app.run(host='0.0.0.0', port=7920)