import os
import requests
import re
import time
import json
import boto3
import urllib
import pandas as pd
from os.path import join, dirname, abspath
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from tempfile import mkdtemp

def handler(event, content):
    def URL(i):
        return f'https://players.pokemon-card.com/event/search?keyword=ビクティニ&prefecture=21&prefecture=22&prefecture=23&prefecture=24&prefecture=25&prefecture=26&prefecture=27&prefecture=28&offset={20*i}&accepting=true&order=1'

    url0 = URL(0)

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

    #seleniumでのUserAgentを変更
    options = webdriver.ChromeOptions()
    service = webdriver.ChromeService("/opt/chromedriver")

    options.binary_location = '/opt/chrome/chrome'
    options.add_argument("--headless=new")
    options.add_argument('--no-sandbox')
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1696")
    options.add_argument("--single-process")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-dev-tools")
    options.add_argument("--no-zygote")
    options.add_argument(f"--user-data-dir={mkdtemp()}")
    options.add_argument(f"--data-path={mkdtemp()}")
    options.add_argument(f"--disk-cache-dir={mkdtemp()}")
    options.add_argument("--remote-debugging-port=9222")

    driver = webdriver.Chrome(options=options, service=service)

    driver.get(url0)
    time.sleep(20)

    content = driver.page_source
    soup = BeautifulSoup(content, 'html.parser')


    topEntry = soup.find('div', attrs={'class': 'searchList'})

    #検索結果のページ数を取得
    if pages := soup.find('div', attrs = {'class': 'searchResult'}):
        pages = pages.text
        pages = re.findall(r'\d+', pages)
        page_num = int(pages[1])
    else:
        page_num = 1

    #leftは日時と県の情報を含む
    lefts = topEntry.find_all('div', attrs={'class': 'left'})

    #rightはステータスと店名の情報を含む
    rights = topEntry.find_all('div', attrs={'class': 'right'})

    #urlも取得
    urls = topEntry.find_all('a', attrs={'class': 'eventListItem'})

    new_df = pd.DataFrame()

    #検索結果のPページ目について情報を抽出
    def dfmaker(L, P):
        for i, left in enumerate(L):
            date = left.find('div', attrs={'class': 'date'}).text
            time = left.find('span', attrs={'class': 'time'}).text
            pref = left.find('span', attrs={'class': 'pref'}).text
            title = rights[i].find('div', attrs={'class': 'title'}).text
            #status = rights[i].find('div', attrs={'class': 'status'}).text
            shop = rights[i].find('div', attrs={'class': 'shop'}).text
            url = urls[i].get('href')
            long_url = urllib.parse.urljoin(URL(P), url)

            c = 20*(P-1)
            new_df.at[i+c, 'title'] = title
            new_df.at[i+c, 'pref'] = pref
            new_df.at[i+c, 'shop'] = shop
            new_df.at[i+c, 'date'] = date
            new_df.at[i+c, 'time'] = time
            new_df.at[i+c, 'url'] = long_url

    dfmaker(lefts, 1)

    if page_num > 1:
        for j in range(1, page_num):
            url_j = URL(j)
            driver.get(url_j)
            #ページの読み込みを待つ
            time.sleep(20)

            content = driver.page_source
            soup = BeautifulSoup(content, 'html.parser')
            
            topEntry = soup.find('div', attrs={'class': 'searchList'})

            #leftは日時と県の情報を含む
            lefts = topEntry.find_all('div', attrs={'class': 'left'})

            #rightはステータスと店名の情報を含む
            rights = topEntry.find_all('div', attrs={'class': 'right'})
            
            #urlも取得する
            urls = topEntry.find_all('a', attrs={'class': 'eventListItem'})

            dfmaker(lefts, j+1)

    s3 = boto3.resource('s3')
    bucket_name = 'victini-detector'
    key = 'new_DF.csv'
    s3_object = s3.Object(bucket_name, key)

    #一回前のデータをold_dfとして読み込む
    old_df = pd.read_csv(s3_object.get()['Body'])

    dotenv_path = join(dirname(abspath("__file__")), '.env')
    load_dotenv(dotenv_path, verbose=True)

    webhook_url = os.getenv('Discord_WebHook_url')

    headers = {
        'Content-Type': 'application/json'
    }
   
    for new_row in new_df.itertuples():
        found = False
        for old_row in old_df.itertuples():
            if old_row[1:7] == new_row[1:7]:
                found = True
        if found == False:
            #newsの要素についてDiscordに通知
            name = new_row.pref + new_row.shop
            value = new_row.date + new_row.time
            message = {

            'embeds': [
                {
                    'title': new_row.title,
                    'description':'先着受付中になったお店があります！',
                    'color' : 0x00ff00,
                    'fields':[
                        {'name': name, 'value': value},
                        {'name': new_row.url, 'value': ''}
                    ]
                }
            ]
        }
            response = requests.post(webhook_url, data=json.dumps(message), headers=headers)
    
    # print(news)

    #次回の実行で使用するcsvをs3へ保存
    result = s3_object.put(Body=new_df.to_csv(None, index=None).encode('utf-8'))

    driver.quit() #ver2で追加、ウェブドライバーの終了処理


