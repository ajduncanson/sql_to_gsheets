
"""atwood product components

Queries our AWS DBs and writes to the Product Listings on Atwood report in google sheets.

Run this file from within the /code dir of the project

"""
#%% 
# setup

import os
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import pytz
import pickle
from sqlalchemy import create_engine
import pygsheets

import atwood_product_listings_report_config as config

tz = pytz.timezone('Australia/Sydney')
filesavetime = datetime.now(tz).strftime("%Y%m%d_%H%M")
today_date = date.today()
pageview_date = (today_date - timedelta(days=7)).strftime("%Y-%m-%d")

# file save details
curpath = os.path.abspath(os.curdir)
data_raw_path = curpath + '/../data/raw/'
data_proc_path = curpath + '/../data/atwood_products/'

if os.path.exists(data_proc_path + "success.txt"):
    os.remove(data_proc_path + "success.txt")
if os.path.exists(data_proc_path + "error.txt"):
    os.remove(data_proc_path + "error.txt")


#%%
# functions

def sqlEngineCreator(user, pword, host, db):

    username = config.cred_info[user]
    password = config.cred_info[pword]
    host = config.cred_info[host]
    db = config.cred_info[db]
    sqlEngine = create_engine(f'mysql+pymysql://{username}:{password}@{host}/{db}') #, pool_size=20, max_overflow=0)
    return sqlEngine

#%% 
# connections
gsheet_key = config.cred_info['gsheet_key']

#%%
# define DB queries

prod_table = {'HomeLoan': 'home_loans',
              'SavingsAccount': 'savings_accounts',
              'TermDeposit': 'term_deposits',
              'BankAccount': 'bank_accounts',
              'DebitCard': 'bank_accounts',
              'PersonalLoan': 'personal_loans',
              'CarLoan': 'personal_loans',
              'CreditCard': 'credit_cards',
              'RewardsCreditCard': 'credit_cards',
              'BusinessLoan': 'business_loans',
              'InternationalMoneyTransfer': 'international_money_transfers',
              'ShareAccount': 'share_accounts',
              'MarginLoan': 'margin_loans',
              'CarInsurance': 'car_insurances',
              'HomeInsurance': 'home_insurances',
              'TravelInsurance': 'travel_insurances',
              'PetInsurance': 'pet_insurances',
              'LandlordInsurance': 'landlord_insurances',
              'LifeInsurance': 'life_insurances',
              'Superannuation': 'superannuations'
              }

# note: the function select_query was fixed on 2025-02-14 to correct a bug. Was previously assessing recency using last_updated_at instead of the correct page_last_updated field.
# at some point in August 2024, last_updated_at stopped working and pages started to be mis-characterised in terms of recency. 

def select_query(prod):
    query = f"""
    select distinct t.product_id AS product_id, t.provider AS provider, t.product_name AS product_name,
    t.page_last_updated AS page_last_updated, t.recency AS recency, t.page_link AS page_link,
    t.page_author, 
    case when t.last_updater is NULL then 'unknown' else t.last_updater end as last_updater, 
    t.atwood_template
    from 
    (select `a`.`id` AS `product_id`,`prov`.`name` AS `provider`,`a`.`name` AS `product_name`,
    (case when (`p`.`page_updated_at` is null) then `p`.`published_at` else `p`.`page_updated_at` end) AS `page_last_updated`,
    (case when ((`p`.`page_updated_at` is null) or ((to_days(now()) - to_days(`p`.`page_updated_at`)) < 180) or regexp_like(`p`.`path`, '^/best')) then 3 else 1 end) AS `recency`,
    concat('https://mozo.com.au',`p`.`path`) AS `page_link`,
    ca.name AS page_author,
    au.name AS last_updater,
    ct.name AS atwood_template
    from 
    (`ferris_production`.`cms_entities` `e` 
    left join `ferris_production`.`cms_pages` `p` on (`e`.`cms_page_id` = `p`.`id`)

    left join cms_authors_pages cap  
    on p.id = cap.cms_page_id    
    
    left join cms_authors ca  
    on cap.cms_author_id = ca.id
    
    left join atwood_users au
    on p.updater_id = au.id

    left join cms_templates ct 
    on p.cms_template_id = ct.id

    left join `ferris_production`.`cms_component_entities` `ce` on (`e`.`cms_component_entity_id` = `ce`.`id`) 
    left join (
        select `ferris_production`.`cms_entities`.`cms_component_entity_id` AS `id`, 
        1 AS `flag` 
        from `ferris_production`.`cms_entities` 
        where ((`ferris_production`.`cms_entities`.`cms_component_prop_id` in (81, 381)) 
            and (`ferris_production`.`cms_entities`.`published_content` = '{prod}'))
        ) `entity_list` 
        on (`e`.`cms_component_entity_id` = `entity_list`.`id`)
    )
    left join `ferris_production`.`{prod_table[prod]}` `a` on(`e`.`published_content` = `a`.`id`) 
    left join `ferris_production`.`providers` `prov` on (`a`.`provider_id` = `prov`.`id`)  
    where ((`e`.`cms_component_prop_id` in (83, 382)) and (`e`.`published_content` is not null) and (`p`.`is_published` = 1) and (`ce`.`hidden` = 0) and (`entity_list`.`flag` = 1)) 
    order by `recency` desc,`prov`.`name`,`a`.`name`,`e`.`cms_page_id`) `t`
    """
    ### explanation of codes:
        ### for product listing components:
        # cms_entities.cms_component_prop_id = 81; ie entity has component property = 'product_type'; when matched with cms_entities.published_content = 'HomeLoan' this denotes product_type = 'HomeLoan.
        # cms_entities.cms_component_prop_id = 83; ie entity has component property = 'product'; when matched with cms_entities.published_content = 123 this denotes product_id = 123.

        ### for editorial reviews on PPT pages:
        # cms_entities.cms_component_prop_id = 381; ie entity has component property = 'product_type'; when matched with cms_entities.published_content = 'HomeLoan' this denotes product_type = 'HomeLoan.
        # cms_entities.cms_component_prop_id = 382; ie entity has component property = 'product'; when matched with cms_entities.published_content = 123 this denotes product_id = 123.
    return query


# def pageview_query(d):
#     query = f"""
#     select 
#     REGEXP_REPLACE(page, '[?].*$', '') as page,
#     sum(case when (sub_channel = 'Search(Google)') or (sub_channel = 'Search(Bing)') then 1 else 0 end) as pageviews_search,
#     sum(case when (sub_channel = 'Organic') or (sub_channel = 'Direct') then 1 else 0 end) as pageviews_organic_direct,
#     sum(case when (sub_channel != 'Organic') and (sub_channel != 'Direct') and (sub_channel != 'Search') then 1 else 0 end) as pageviews_other_paid,
#     count(*) as pageviews_7_days      
#     FROM
#         ferris_tableau.rcd
#         where 
#         source = 'ga' 
#         and page not like '/gts%%'
#         and `date` >= '{d}'              
#     group by REGEXP_REPLACE(page, '[?].*$', '')
#     """
#     return query


# def test_query():
#     query = f"""
#     select * from ferris_tableau.provider_name
#     """
#     return query


#%%
# get ethercat data

product_types = prod_table.keys()
##['HomeLoan', 'SavingsAccount', 'CarLoan'] #, 'PL', 'TD']

result = dict()
error_flag = False

# connection to current db list of endpoints
sqlEngine = sqlEngineCreator('ethercat_username', 'ethercat_password', 'ethercat_host', 'ethercat_db')
#%%
try:
    for prod in product_types:

        # test    prod = 'TravelInsurance'
        with sqlEngine.connect() as dbConnection:
            query = select_query(prod)
            db_results = pd.read_sql(sql=query, con=dbConnection)
            result[prod] = db_results

except:
    error_flag = True

#%% 
# get pageview data ---- ##### removed, as rcd ga no longer available

# # connection to db activity data
# sqlEngine = sqlEngineCreator('aircamel_rep_username', 'aircamel_rep_password', 'aircamel_rep_host', 'aircamel_rep_db')

# try:  
#     with sqlEngine.connect() as dbConnection:
#         query = pageview_query(pageview_date)
#         pageview_result = pd.read_sql(sql=query, con=dbConnection)
#         pageview_result['page'] = ['https://mozo.com.au' + p for p in pageview_result['page']]
# except:
#     error_flag = True

# %%
# save to gsheets

try:

    #authorization
    gc = pygsheets.authorize(service_file='../auth/mozo-private-dev-19de22e18578.json')
    sh = gc.open_by_key(gsheet_key)
    # note that the Sheets file must be shared with pygsheets@mozo-private-dev.iam.gserviceaccount.com
    #update the raw data sheets, starting at cell A1. 

    #also create union file to be used by product changes report
    result_union = pd.DataFrame()

    for prod in product_types:

        # test    prod = 'HomeLoan'  

        this_result = result[prod]
        ####### removed; used ga pageviews
            # this_result = this_result.merge(pageview_result, how = 'left', left_on = 'page_link', right_on = 'page')
            # this_result = this_result.drop(columns=['page'])
        this_result = this_result.fillna(0)

        # write to gsheets
        wks = sh.worksheet_by_title(prod + ' raw data')
        wks.clear(start='A1', end=None, fields='*')
        wks.set_dataframe(this_result,(1,1))

        # append pageviews data to result_union
        this_result['product_type'] = prod
        result_union = pd.concat([result_union, this_result], axis = 0)

    #updated the latest date
    wks = sh.worksheet_by_title('cover')
    wks.update_value((2,3), filesavetime)

    #save the latest union of atwood products
    result_union.to_csv(data_proc_path + 'atwood_products_latest.csv')

except:
    error_flag = True

# %%
# save pickle

# fname = 'atwood_product_listings'
# pname = data_proc_path + fname + '_' + filesavetime + '.pkl'
# with open(pname, 'wb') as file: 
#     pickle.dump(result, file) 


# %%
# error flag file to drive shell script email reporting
    
if error_flag:
    if os.path.exists(data_proc_path + "success.txt"):
        os.remove(data_proc_path + "success.txt")
    f = open(data_proc_path + "error.txt", "a")
    f.write("error " + filesavetime)
    f.close()
else:
    if os.path.exists(data_proc_path + "error.txt"):
        os.remove(data_proc_path + "error.txt")
    f = open(data_proc_path + "success.txt", "a")
    f.write("success " + filesavetime)
    f.close()



# %%
