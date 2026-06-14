from fastapi import FastAPI, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware # Needed for Step 2
from typing import List # Needed for your multiple images array
from PIL import Image
import base64
from dotenv import load_dotenv
import os
from openai import OpenAI
import json
import pandas as pd
import boto3
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
EBAY_TEMPLATE_PATH = BASE_DIR / "ebay-temp.csv"
EBAY_OUTPUT_PATH = BASE_DIR / "ebay-new.csv"
EBAY_ACTION_COLUMN = "*Action(SiteID=UK|Country=GB|Currency=GBP|Version=1193|CC=UTF-8)"
EBAY_ITEM_LOCATION = os.getenv("EBAY_ITEM_LOCATION", "London")
EBAY_SHIPPING_PROFILE_ID = os.getenv("EBAY_SHIPPING_PROFILE_ID", "396482100023")
EBAY_PAYMENT_PROFILE_ID = os.getenv("EBAY_PAYMENT_PROFILE_ID", "396481420023")
EBAY_RETURN_PROFILE_ID = os.getenv("EBAY_RETURN_PROFILE_ID", "396481523023")


def ebay_specific_column(field_name: str) -> str:
    if field_name.startswith("C:"):
        return field_name
    return f"C:{field_name}"



GLOBAL_PRODUCTS_QUEUE = []

MOCK_MODE = False




load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,  # CORS(set the rule of who can coming to talk to backend)

     # Tells browsers it's safe to send data here, as * means everyone, 
     # but in real world can be     allow_origins=["http://localhost:3000"],  # ← Allow only this frontend
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],  # Allows all actions (POST, GET, etc.)
    allow_headers=["*"],  # Allows all types of headers
)


# 初始化 S3 客户端（它会自动读取 .env 里的那三个 AWS 变量）
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "eu-north-1")
)


#  ebay--------------------------------------------------------------------------


    # get the application token, by using the two  password, this is becasue ebay use oauth 2.0 which without
    #sharing the real password
def get_ebay_application_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    
    # 1. Base64 encode the Client ID and Client Secret together
    credentials = f"{client_id}:{client_secret}"
    encoded_creds = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    
    # 2. eBay Sandbox OAuth Endpoint
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_creds}"
    }
    
    # 3. Requesting scoping for public metadata (Taxonomy API access)
    payload = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    
    print("Requesting  access token...")

    # request is a python function allow to send http request to the webiste/API , just like fetch in js.
    response = requests.post(url, headers=headers, data=payload, timeout=20)

    print("Status code:", response.status_code)
    # print(response.json()["access_token"]) # this will show the token(application access token), and the expires time which is about 7200 seconds 

    return response.json()["access_token"]


def get_uk_category_tree_id(access_token):

    # 1. Define the Endpoint (Remember to use 'sandbox' for testing!)
    url = "https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id/"

    # 2. Package your authorization rule
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # 3. Package your market filter rule
    params = {
        "marketplace_id": "EBAY_GB"
    }

    # 4. Fire the request tool using all three ingredients
    response = requests.get(url, headers=headers, params=params)

    return response.json()["categoryTreeId"]




def fetch_ebay_category_and_aspects(keyword: str):


    access_token =get_ebay_application_token()

    ebay_id =get_uk_category_tree_id(access_token)


    suggestion_url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{ebay_id}/get_category_suggestions"


    header = {
        "Authorization": f"Bearer {access_token}",
        "Accept-Language": "en-GB" # Target eBay UK
    }

    params = {
        "q" : keyword

    }

    response =requests.get(suggestion_url,headers=header,params=params)

    best_matches = response.json()

    return best_matches




def ebay_blank_form(category_id: str, access_token: str) -> list: 


            url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/3/get_item_aspects_for_category"

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Accept-Language": "en-GB"  # 🌟 锁死 eBay UK：确保返回的是英式英语（如 Colour, Tyre），防错报
            }
    
            params = {
                "category_id": category_id
            }


            response = requests.get(url,headers=headers,params=params,timeout=20)

            aspects_data = response.json()

            aspects_data = aspects_data.get("aspects",[])

            blank_fields = [] # ->["Brand", "Model", "Type", "Maximum Flight Time", "Connectivity", "Camera Features"]


         # 1. 因为 eBay 返回的最外层是一个字典，里面有一个叫 "aspects" 的列表。
         # 这句话的意思是：遍历这个列表里的每一个属性格。
            for aspect in aspects_data :

                # 2. 从当前属性里，把它的官方名字拿出来（比如拿到了 "Brand" 或者 "Colour"）
                aspect_name = aspect.get("localizedAspectName")
                
                # 3. 深入进去，拿到控制这个属性的“约束条件”字典
                constraint = aspect.get("aspectConstraint", {})
                
                # 4. 在约束条件里，查看这个字段的“使用频率/重要程度”（usage）
                #    eBay 会标记它是 'REQUIRED'（必填）、'RECOMMENDED'（推荐）还是 'OPTIONAL'（可选）
                usage = constraint.get("aspectUsage")  
                
                # 5. 核心过滤关卡：
                #    如果这个字段是 eBay 规定【必填】或【强烈推荐】的，并且它确实有名字
                if usage in ["REQUIRED", "RECOMMENDED"] and aspect_name:
                    
                    # 6. 那就通过过关验证！把它存进我们的空白表单列表里
                    blank_fields.append(aspect_name)

            return blank_fields












 # when someone sends a POST request to /submit, please run the function below.
@app.post("/submit")

 #去请求里找一个普通字段 price
 #去请求里找文件字段 images
async def receive_product(price: float = Form(...), images: List[UploadFile] = File(...)):  
    print(f"收到商品价格: {price} £")

    image_container = []
    imageContent = [] 
    first_image = images[0]
   

    for img in images:
        read_temp = await img.read()
        imageContent.append(read_temp)
        image_container.append(base64.b64encode(read_temp).decode("utf-8"))
        # 先用 b64encode 把图片的二进制字节（Bytes）压缩成 Base64 编码，再用 .decode("utf-8") 把这个编码转换成纯文本的字符串（String）。因为 OpenAI 的 API 只接受字符串格式的 Base64，不能直接接收原始的二进制数据。
        
    
    user_content = [ { "type": "text","text": "Please inspect this packaging image and output the Stage 1 identification JSON object."
         }]
        

    for img in image_container:
        user_content.append({"type": "image_url", "image_url" : {"url": f"data:{first_image.content_type};base64,{img}"}})



    
    # testImages = images[0]

    # # 在内存中把这张图片读取出来，并转换成 Base64 字符串
    # imageContent = await testImages.read()
    # imageEncode = base64.b64encode(imageContent).decode("utf-8")




    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
    
        if MOCK_MODE:
            print("MOCK MODE")
            ai_suggestion = '{"title": "Mock Product Title For Test", "description": "This is a fake description used for testing frontend and CSV export without calling OpenAI API."}'

        else:
           response = client.chat.completions.create(
    model="gpt-4o",
    response_format={ "type": "json_object" },
    messages=[
        {
            "role": "system",
            "content": (
                "You are an expert product identification assistant. Your ONLY job is to look at the product packaging image "
                "and extract the identity of the item into a strict JSON format.\n\n"

                "CRITICAL RULES:\n"
                "1. Identify the product name and type SOLELY based on the text and graphics visible on the packaging box. DO NOT guess or assume details.\n"
                "2. 'search_keyword' MUST be a clean, concise 2-4 word phrase containing just the Brand + Core Product Type (e.g., 'Anker USB Hub', 'Logitech Mouse'). Do not include descriptors like 'New', 'Great', or item conditions.\n"
                "3. 'title' MUST be a clean, search-optimized eBay title under 80 characters (ideally around 70) using the extracted brand, model number, and primary keywords visible on the box.\n\n"

                "OUTPUT FORMAT:\n"
                "You must respond with a strict JSON object containing EXACTLY these 2 keys. "
                "Do not include any markdown formatting like ```json or any introductory text.\n"
                "{\n"
                '  "search_keyword": "A concise 2-4 word brand and product phrase for eBay directory search.",\n'
                '  "title": "A search-optimized eBay title under 80 characters using extracted box text."\n'
                "}"
            )
        },
        {
            "role": "user",
            "content": user_content,
        }
    ],
)
           
            
        
        # 4. 抓取 AI 生成的文案结果
        ai_suggestion = response.choices[0].message.content
        
        print("AI 成功生成描述！")
        print("AI resonse :", ai_suggestion )




        #字符串变成 Python 字典,因为AI给的response 还是string
        ai_suggestion_dic = json.loads(ai_suggestion)


        print("开始上传图片到 S3")


        bucket_name = os.getenv("AWS_STORAGE_BUCKET_NAME", "leheng-my-storage-2026-915093573061-eu-north-1-an")
        region = os.getenv("AWS_REGION", "eu-north-1")

        public_url_container = []

        for i, img in enumerate(images):
            s3_path_name = f"products/{img.filename}"

            s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_path_name,
            Body=imageContent[i],             # 直接复用之前已经 read() 好的 imageContent
            ContentType=img.content_type, # 保持图片的真实格式 (png/jpeg),告诉亚马逊这是一张图片（比如 image/jpeg）
        )

            public_image_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_path_name}"
            public_url_container.append(public_image_url)

            print(f"📸 图片成功上传云端！公开链接为: {public_image_url}")
        # use join to add ! so ebay can read in one go
        public_url_container = "!".join(public_url_container)
        
        

     
    
        access_token = get_ebay_application_token()

        ebay_suggestions = fetch_ebay_category_and_aspects(ai_suggestion_dic["search_keyword"])

        # print("ebay suggestion:", ebay_suggestions)



        suggestions = ebay_suggestions.get("categorySuggestions", [])

        first_suggestion = suggestions[0]["category"]

        suggestions_id = first_suggestion["categoryId"]

        


        official_blank_form = ebay_blank_form(suggestions_id,access_token)

    # ==========================================
        # STAGE 2: 拿着 eBay 官方清单，让 AI 第二次精准看图填空
        # ==========================================
        
        # 1. 把列表变成一句话给 AI 看，例如: "Brand, Model, Type, Colour"
        fields_needed_str = ", ".join(official_blank_form)
        
        print(f"正在启动 Stage 2,命令 AI 提取这些字段: {fields_needed_str}")


        user_content_for_second_ai = [ { "type": "text","text": f"Please look at the image and fill in these exact fields: [{fields_needed_str}]. Also provide the 'description'."

         }]
        
        for img in image_container:
            user_content_for_second_ai.append({"type": "image_url", "image_url" : {"url": f"data:{first_image.content_type};base64,{img}"}})


        
        stage2_response = client.chat.completions.create(
            model="gpt-4o",
            response_format={ "type": "json_object" },
            messages=[
                {
                    "role": "system",
                "content": (
                        "You are a precise data entry assistant. The user will provide you with a product packaging image, "
                        "and a list of official fields that eBay requires for this item.\n\n"
                        
                        "YOUR TASK:\n"
                        "1. Look at the packaging image very carefully.\n"
                        # 🌟 这里的规则改掉：除 Brand 外，其余找不到的全部返回 'See Image'
                        "2. Extract the true value for each requested field. If Brand is not visible, return 'Unbranded'. If any other field is not visible on the box at all, strictly return 'See Image'.\n"
                        "3. Generate a concise, professional description based ONLY on visible text (100-200 characters max, no HTML).\n\n"
                        
                        "OUTPUT FORMAT:\n"
                        "You must return a strict JSON object with EXACTLY two keys: 'description' and 'specifics'.\n"
                        "Inside 'specifics', you MUST use the exact field names provided by the user as keys.\n"
                        "Do not use markdown formatting."
                    )
                },
                {
                    "role": "user",
                    "content": user_content_for_second_ai,
                }
            ],
        )
        
        # 2. 解析 Stage 2 完美的 JSON 结果
        stage2_data = json.loads(stage2_response.choices[0].message.content)
        print("🎉 Stage 2 AI 填空结果:", stage2_data)

        # 大概会打印这个东西
        #         {
        #   "description": "Genuine Logitech MX Master 3 wireless mouse in black. Supports Bluetooth and 2.4GHz wireless connection.",
        #   "specifics": {
        #     "Brand": "Logitech",
        #     "Model": "MX Master 3",
        #     "Type": "Ergonomic Mouse",
        #     "Colour": "Black"
        #   }
        # }



        final_products = {
            "price" : price,
            "title" : ai_suggestion_dic["title"],
            "keyword": ai_suggestion_dic["search_keyword"],
            
            "description" : stage2_data["description"],
            "image_url": public_image_url # 把云端的真实直链带给前端展示

        }



        GLOBAL_PRODUCTS_QUEUE.append(final_products)
        
        

        # 1. 用纯文本方式读取并保留第 0 行的 Info 头信息, e.g Info,Version=1.0.0,Template=fx_category_template_EBAY_GB
        with open(EBAY_TEMPLATE_PATH, "r", encoding="utf-8-sig") as f:
            first_line = f.readline()


        df_old = None

        file_is_empty = (not os.path.exists(EBAY_OUTPUT_PATH)) or (os.path.getsize(EBAY_OUTPUT_PATH) == 0)

        if os.path.getsize(EBAY_OUTPUT_PATH) == 0:
            # python 里的read file 读取了frist line, 如果下一次用    second_line = f.readline() 就会读取第二line 而不是第一line
            # 这个是因为pointer 已经移到了next line了
            #  open the new csv, which is ebay-new.csv, 
            # and write the first_line from the previous read operation , then write into the frist line
            with open(EBAY_OUTPUT_PATH, "w", encoding="utf-8") as nf:
                nf.write(first_line)

            # write operation will clean all the previous data

    

        # 1. 临时读取原文件的结构（header=1 表示把第2行，也就是索引为1的那一行当作表头），跳过第 1 行那句没用的系统配置
         #  *Action(SiteID=UK|Country=GB|Currency=GBP|Version=1193|CC=UTF-8)|   CustomLabel
        #   infor                                                              >>> Get more details.......
        #   infor  
        #   infor   
        
        df_old = pd.read_csv(EBAY_TEMPLATE_PATH, header=1)




        new_items = {
            EBAY_ACTION_COLUMN: "Add",  # 或 "Add"
            "*Category":  suggestions_id,                    # AI 动态预测的分类 ID

            # 2. 商品基本信息
            "*Title": ai_suggestion_dic["title"] ,               # AI 生成的 70 字左右标题
            "*ConditionID": "1000",                                                         # 全新状态码固定为 "1000"

            # 3. 商品详情描述
            "*Description": stage2_data["description"] ,               # AI 生成的规格描述
            # 🌟 填坑：精准将 AWS S3 的网络直链绑定到官方模板的 PicURL 这一格！
            "PicURL": public_url_container,

            # 4. 销售政策
            "*Format": "FixedPrice",                                                        # 一口价模式
            "*Duration": "GTC",                                                             # 长期在线直到卖完
            "*StartPrice": price,                                       # 商品售价
            "*Quantity": "1",                                                               # 库存数量
            "*Location": EBAY_ITEM_LOCATION,                                                # 商品所在地，例如 London

            "ShippingProfileID": EBAY_SHIPPING_PROFILE_ID,
            "PaymentProfileID": EBAY_PAYMENT_PROFILE_ID,
            "ReturnProfileID": EBAY_RETURN_PROFILE_ID,
            "Product:EAN": "Does not apply",
            } 
        
        specifics_data_from_ebay = stage2_data["specifics"]

        for key,value in specifics_data_from_ebay.items():
            new_items[ebay_specific_column(key)] = value
       

        
        #：把上面那条新商品的数据，塞进方括号 [...] 变成一个list，然后通过 pd.DataFrame() 转换成一个 DataFrame（内存中的电子表格）。
        #  如果里面是这样子  "*Category":  [suggestions_id, suggestion_id2] 就可以不用放在list            
        df_new = pd.DataFrame([new_items])


        df_combined = pd.concat([df_new,df_old],ignore_index=True)
        #，concat 把数据行上下拼，不会动表头的位置, 所以把新的数据（就是产品的数据放在前面）。 旧的数据放在后面（就是剩下的那些info 的内容）
        # 但是会把新的数据的标题都放在最左边，剩下的没有提到的放在右边。



        df_ebay_suggestion = pd.DataFrame([stage2_data])
        
        df_final = pd.concat([df_ebay_suggestion,df_combined])




        all_current_columns = list(dict.fromkeys(df_old.columns.tolist() + df_new.columns.tolist()))
        df_final = df_combined.reindex(columns=all_current_columns)

        df_only_new_row = df_final.head(1)
        

        df_final.to_csv(
        EBAY_OUTPUT_PATH,          # 1. 保存的目的地新文件名

        mode='a',          # 2. 写入模式：'a' 代表 Append（追加粘贴）
                       #    【细节】：意思是“不覆盖旧内容，在文件屁股后面接着写”。这里用来紧跟在第一行 eBay 暗号的下面。
                       #    【Example】: 文件里本来有 "Info,Version=1.0..."，执行后，数据会从第二行开始无缝拼接。

        index=False,       # 3. 是否保存隐藏行号：False 代表“不要保存”
                       #    【细节】：Pandas 默认会在表格最左边自动生成一列 0,1,2,3 的数字，必须把它关掉。
                       #    【Example】: 如果设为 True，表格最左边会平白无故多出一列数字，上传 eBay 就会直接报错。

        header=file_is_empty,       # 4. 是否写入大表头（列名）：True 代表“要写入”
                       #    # 【细节】：因为新文件现在只有一句话，所以我们必须把商品属性的这一行标题写进去。
                       #    【Example】: 会在暗号下面写入一行 "*Action, CustomLabel, *Category, *Title"。

        encoding='utf-8'  
)
        
        return{
            "success" : True,
            "message" : "products created successfully",
            "data" : final_products
        }




        
    except Exception as e:
        print(f"后段服务报错了: {e}")
        return {
            "success" : False,
            "message" : f"Server Error: {str(e)}",
            "data" : None
                                        

        }

    
