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


BASE_DIR = Path(__file__).resolve().parent
EBAY_TEMPLATE_PATH = BASE_DIR / "ebay-temp.csv"
EBAY_OUTPUT_PATH = BASE_DIR / "ebay-new.csv"
EBAY_ACTION_COLUMN = "*Action(SiteID=UK|Country=GB|Currency=GBP|Version=1193|CC=UTF-8)"
EBAY_ITEM_LOCATION = os.getenv("EBAY_ITEM_LOCATION", "London")
EBAY_SHIPPING_PROFILE_ID = os.getenv("EBAY_SHIPPING_PROFILE_ID", "396482100023")
EBAY_PAYMENT_PROFILE_ID = os.getenv("EBAY_PAYMENT_PROFILE_ID", "396481420023")
EBAY_RETURN_PROFILE_ID = os.getenv("EBAY_RETURN_PROFILE_ID", "396481523023")


def normalise_item_specifics(ai_suggestion_dic):
    specifics = ai_suggestion_dic.setdefault("specifics", {})

    if not specifics.get("C:Brand"):
        specifics["C:Brand"] = "Unbranded"

    if not specifics.get("C:Type"):
        specifics["C:Type"] = "Unit"

    if not specifics.get("C:Model"):
        specifics["C:Model"] = "Does Not Apply"

    return specifics


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





 # when someone sends a POST request to /submit, please run the function below.
@app.post("/submit")

 #去请求里找一个普通字段 price
 #去请求里找文件字段 images
async def receive_product(price: float = Form(...), images: List[UploadFile] = File(...)):  
    print(f"收到商品价格: {price} £")
    
    testImages = images[0]

    # 在内存中把这张图片读取出来，并转换成 Base64 字符串
    imageContent = await testImages.read()
    imageEncode = base64.b64encode(imageContent).decode("utf-8")




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
                "You are a strict eBay listing assistant. The user will ONLY provide you with a product packaging image and a listing price. "
                "Your job is to look at the image and extract factual information to generate a flawless eBay listing in a strict JSON format.\n\n"

                "CRITICAL ACCURACY RULES:\n"
                "1. Identify the product SOLELY based on the text and graphics visible on the packaging box in the image. DO NOT guess or invent features.\n"
                "2. Keep the tone completely objective, factual, and strictly based on the box. No creative writing or exaggeration.\n\n"

                "EBAY UK SPECIFIC COMPLIANCE:\n"
                "1. 'category': Predict the most accurate official numeric eBay UK Category ID based on the product type. If uncertain, choose the most general parent category available on eBay UK.\n"
                "2. 'specifics': Dynamically generate the most relevant item specifics as many as needed for this category.\n"
                "   - Every key MUST be prefixed with 'C:' (e.g., 'C:Brand', 'C:Type', 'C:Model', 'C:Color', 'C:MPN').\n"
                "   - You MUST use official eBay naming conventions for keys (CamelCase, standard English). NEVER invent your own keys.\n"
                "   - For 'C:Brand', if no brand is clearly visible on the box, you MUST strictly return 'Unbranded'.\n"
                "   - For 'C:Type', provide a 1-2 word standard product type (e.g., 'Drone', 'Fan', 'Adapter').\n"
                "   - You MUST always include 'C:Model'. If no model is clearly visible, return 'Does Not Apply'. Never omit 'C:Model'.\n\n"

                "OUTPUT FORMAT:\n"
                "You must respond with a strict JSON object containing EXACTLY these 4 keys. "
                "Do not include any markdown formatting like ```json or any introductory text.\n"
                "{\n"
                '  "title": "A search-optimized eBay title based on visible brand/model. MUST be under 80 characters, ideally around 70. NO promotional words like Great or New.",\n'
                '  "description": "A professional and concise product summary based ONLY on what is explicitly visible on the packaging. 100-200 characters max. No HTML. No invented details.",\n'
                '  "category": "A pure numeric string representing the eBay Category ID.",\n'
                '  "specifics": {\n'
                '    "C:Brand": "Brand Name or Unbranded",\n'
                '    "C:Type": "Product Type",\n'
                '    "C:Model": "Model Number if visible, otherwise Does Not Apply"\n'
                "  }\n"
                "}"
            )
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"This item is being listed for {price} GBP. Please look at the image of the packaging box and generate the required JSON object following the strict rules."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{testImages.content_type};base64,{imageEncode}"
                    },
                },
            ],
        }
    ],
)
        
        # 4. 抓取 AI 生成的文案结果
        ai_suggestion = response.choices[0].message.content
        
        print("AI 成功生成描述！")
        print("AI resonse :", ai_suggestion )




        #字符串变成 Python 字典,因为AI给的response 还是string
        ai_suggestion_dic = json.loads(ai_suggestion)
        normalise_item_specifics(ai_suggestion_dic)


        print("开始上传图片到 S3")


        bucket_name = os.getenv("AWS_STORAGE_BUCKET_NAME", "leheng-my-storage-2026-915093573061-eu-north-1-an")
        region = os.getenv("AWS_REGION", "eu-north-1")

        # 这是文件在网盘里的路径和名字。加上 products/ 前缀，就像是在网盘里建了一个名为 “products” 的文件夹，把图片放进去，让文件分类更整洁。
        s3_path_name = f"products/{testImages.filename}"

        #执行上传（把货塞进亚马逊的仓库）
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_path_name,
            Body=imageContent,             # 直接复用之前已经 read() 好的 imageContent
            ContentType=testImages.content_type, # 保持图片的真实格式 (png/jpeg),告诉亚马逊这是一张图片（比如 image/jpeg）
        )

        #按照亚马逊 S3 的固定域名格式，把你的网盘名、地区和文件名拼接成一个标准的网址。
        public_image_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_path_name}"


        print(f"📸 图片成功上传云端！公开链接为: {public_image_url}")

     
        

   

        final_products = {
            "price" : price,
            "title" : ai_suggestion_dic["title"],
            "description" : ai_suggestion_dic["description"],
            "image_name": testImages.filename,
            "image_url": public_image_url # 把云端的真实直链带给前端展示

        }

        GLOBAL_PRODUCTS_QUEUE.append(final_products)
        
        

        # 1. 用纯文本方式读取并保留第 0 行的 Info 头信息
        with open(EBAY_TEMPLATE_PATH, "r", encoding="utf-8-sig") as f:
            first_line = f.readline()

            # python 里的read file 读取了frist line, 如果下一次用    second_line = f.readline() 就会读取第二line 而不是第一line
            # 这个是因为pointer 已经移到了next line了

        with open(EBAY_OUTPUT_PATH, "w", encoding="utf-8") as nf:
            nf.write(first_line)

    

        # 1. 临时读取原文件的结构（header=1 表示把第2行，也就是索引为1的那一行当作表头），跳过第 1 行那句没用的系统配置
         #  *Action(SiteID=UK|Country=GB|Currency=GBP|Version=1193|CC=UTF-8)|   CustomLabel
        #   infor                                                              >>> Get more details.......
        #   infor  
        #   infor   
        df_old = pd.read_csv(EBAY_TEMPLATE_PATH, header=1)
      

        new_items = [{
            EBAY_ACTION_COLUMN: "VerifyAdd",  # 或 "Add"
            "*Category":  ai_suggestion_dic["category"],                    # AI 动态预测的分类 ID

            # 2. 商品基本信息
            "*Title": ai_suggestion_dic["title"] ,               # AI 生成的 70 字左右标题
            "*ConditionID": "1000",                                                         # 全新状态码固定为 "1000"

            # 3. 商品详情描述
            "*Description": ai_suggestion_dic["description"] ,               # AI 生成的规格描述
            # 🌟 填坑：精准将 AWS S3 的网络直链绑定到官方模板的 PicURL 这一格！
            "PicURL": public_image_url,

            # 4. 销售政策
            "*Format": "FixedPrice",                                                        # 一口价模式
            "*Duration": "GTC",                                                             # 长期在线直到卖完
            "*StartPrice": price,                                       # 商品售价
            "*Quantity": "1",                                                               # 库存数量
            "*Location": EBAY_ITEM_LOCATION,                                                # 商品所在地，例如 London

            "ShippingProfileID": EBAY_SHIPPING_PROFILE_ID,
            "PaymentProfileID": EBAY_PAYMENT_PROFILE_ID,
            "ReturnProfileID": EBAY_RETURN_PROFILE_ID,
            } ]
        


        for key, value in ai_suggestion_dic["specifics"].items():
            new_items[0][key] = value

        
       



        
        #：把上面那条新商品的数据，塞进方括号 [...] 变成一个列表，然后通过 pd.DataFrame() 转换成一个 DataFrame（内存中的电子表格）。
        df_new = pd.DataFrame(new_items)


        df_combined = pd.concat([df_new,df_old],ignore_index=True)
        #，concat 把数据行上下拼，不会动表头的位置, 所以把新的数据（就是产品的数据放在前面）。 旧的数据放在后面（就是剩下的那些info 的内容）
        # 但是会把新的数据的标题都放在最左边，剩下的没有提到的放在右边。


        all_current_columns = list(dict.fromkeys(df_old.columns.tolist() + df_new.columns.tolist()))
        # 强制让拼接后的表格，100% 按照老模板一字不差的左右顺序重新排好坐席
        # df_combined = df_combined.reindex(columns=df_old.columns.tolist()) # 变成基础列表（List）

        df_combined = df_combined.reindex(columns=all_current_columns)



        print(df_combined)
        

        df_combined.to_csv(
        EBAY_OUTPUT_PATH,          # 1. 保存的目的地新文件名

        mode='a',          # 2. 写入模式：'a' 代表 Append（追加粘贴）
                       #    【细节】：意思是“不覆盖旧内容，在文件屁股后面接着写”。这里用来紧跟在第一行 eBay 暗号的下面。
                       #    【Example】: 文件里本来有 "Info,Version=1.0..."，执行后，数据会从第二行开始无缝拼接。

        index=False,       # 3. 是否保存隐藏行号：False 代表“不要保存”
                       #    【细节】：Pandas 默认会在表格最左边自动生成一列 0,1,2,3 的数字，必须把它关掉。
                       #    【Example】: 如果设为 True，表格最左边会平白无故多出一列数字，上传 eBay 就会直接报错。

        header=True,       # 4. 是否写入大表头（列名）：True 代表“要写入”
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

    
