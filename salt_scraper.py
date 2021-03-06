#!/usr/bin/python

import requests
import requests.utils
import code
import datetime
import re
import shutil
import configparser
import tempfile
import logging

from lxml import html
from PyPDF2 import PdfFileReader, PdfFileWriter

def parse_date(date_string):
    return datetime.datetime.strptime(date_string, '%d.%m.%Y').date()


class Bill():

    def __init__(self, period, price, due_date, pdf_url):
        self.period = period
        self.price = price
        self.due_date = due_date
        self.pdf_url = pdf_url

    def __str__(self):
        return str(self.period[0].year) + "-" + str(self.period[0].month)

class SaltScraper():

    def __init__(self, user, password):
        self.base_url = 'https://myaccount.salt.ch'
        self.login_url = 'https://sessions.salt.ch/cas/login'
        self.user = user
        self.password = password
        self.bills = []
        self.session = requests.Session()

    def login(self):
        r = self.session.get(self.login_url)
        r.raise_for_status()
        tree = html.fromstring(r.content)
        values = {}
        for input_element in tree.xpath('//form[@id="idmpform"]//input'):
            values[input_element.name] = input_element.value

        values['username'] = self.user
        values['password'] = self.password

        r = self.session.post(self.login_url, data=values)
        r.raise_for_status()

    def __get_bill_from_element(self, element):
        cols = element.xpath(".//li")
        if len(cols) != 4:
            raise Exception('invalid bill element on line {}'.format(element.sourceline))
        
        dates = cols[0].text.split() # 0 from, 1: "bis", 2: to
        from_date = parse_date(dates[0])
        to_date = parse_date(dates[2])
        due_date = parse_date(cols[2].text.strip())
        price = float(re.sub('[^\d.]', '', cols[1].find("span").text))
        pdf_link_path = cols[3].find("a").get("href")
        pdf_url = '{}{}'.format(self.base_url, pdf_link_path)

        return Bill(period=[from_date, to_date], 
                due_date=due_date,
                price=price,
                pdf_url=pdf_url)

    def get_bills(self):
        r = self.session.get('{}/de/bills/'.format(self.base_url))
        tree = html.fromstring(r.content)
        bill_elements = tree.xpath("//div[@data-at-invoices][1]/ul[contains(@class, 'body-data')]")
        bills = []
        for bill_element in bill_elements:
            bills.append(self.__get_bill_from_element(bill_element))

        self.bills = bills
        return bills

    def get_bill_by_month(self, year, month):
        for bill in self.bills:
            if bill.period[0].year == year and bill.period[0].month == month:
                return bill

    def download_bill(self, bill, fileobj):
        r = self.session.get(bill.pdf_url, stream=True)
        shutil.copyfileobj(r.raw, fileobj)

    def get_payment_detail_pdf(self, src, dest, page=3):
        pdf_reader = PdfFileReader(src)
        pdf_writer = PdfFileWriter()
        pdf_writer.addPage(pdf_reader.getPage(page))
        pdf_writer.write(dest)


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s  %(message)s', level=logging.INFO)
    cfg = configparser.ConfigParser()
    cfg.read("config.cfg")
    s = SaltScraper(cfg.get('DEFAULT', 'username'), cfg.get('DEFAULT', 'password'))

    logging.info("login")
    s.login()

    logging.info("get bills")
    bills = s.get_bills()
    from_date = datetime.date(2018, 5, 1)

    for bill in bills:
        logging.info("{} - {}: {} (pay until {})".format(bill.period[0], bill.period[1], bill.price, bill.due_date))
        if bill.period[0] > from_date:
            logging.info("  -> download bill {}".format(bill))
            with tempfile.TemporaryFile() as f:
                s.download_bill(bill, f)
                f.seek(0)
                with open(str(bill) + ".pdf", "wb") as output:
                    # format changed in june 18
                    if bill.period[0] < datetime.date(2018, 6, 1):
                        s.get_payment_detail_pdf(f, output, page=1)
                    else:
                        s.get_payment_detail_pdf(f, output)
