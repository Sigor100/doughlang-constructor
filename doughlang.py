import io
import os
import discord
import json
import hashlib
import requests
import time
import sys
from PIL import Image, ImageDraw
import numpy as np
import aiohttp
import asyncio
import base64

g_session = None
g_config = {}

def get_sha256(content):
    if type(content) is str:
        content = content.encode('utf-8')
    return hashlib.sha256(content).hexdigest()

def hex_to_color(hx): # returns the color of "#rrggbb" in uint32 form
    r = int(hx[1:3], 16)
    g = int(hx[3:5], 16)
    b = int(hx[5:7], 16)
    return r + (g << 8) + (b << 16) + 0xFF000000 # added constand for alpha=255

def resolve_pallette(name, config=None):
    if config is None:
        config = g_config
    modular_colors = config["modular_colors"]
    if name in config["color_pallettes"]:
        return config["color_pallettes"][name]
    elif len(name.split("-")) == 2:
        c1, c2 = name.split("-")
        if c1 in modular_colors and c2 in modular_colors:
            return ((modular_colors[c2], 0x300c0300), (modular_colors[c1], 0xff3fcff))
    elif name in modular_colors:
        return ((modular_colors[name], 0x3fffffff),)
    return None

def load_config():
    global g_config

    with open("./config.json", "r") as f:
        obj = json.load(f)
    
    new_config = {}
    new_config["glyph_map"] = {}
    for mapping in obj["glyph-mapping"]:
        for i in range(10):
            bits = 0b100000000010000000001 << i
            new_config["glyph_map"][mapping[i]] = bits


    new_config["modular_colors"] = {}
    for name in obj["modular-colors"]:
        new_config["modular_colors"][name] = hex_to_color(obj["modular-colors"][name])
    
    new_config["color_pallettes"] = {}
    for name in obj["color-pallettes"]:
        new_config["color_pallettes"][name] = tuple((hex_to_color(color_key), obj["color-pallettes"][name][color_key]) for color_key in obj["color-pallettes"][name])[::-1]

    fonts = {}
    for name in obj["fonts"]:
        fonts[name] = {}
        cfg_font = obj["fonts"][name]
        with open(cfg_font["source"], "rb") as f:
            fonts[name]["arr"] = np.copy(np.swapaxes(np.load(f), 0, 1))
        fonts[name]["block_offset"] = cfg_font["block-offset"]
        fonts[name]["default_pallette"] = resolve_pallette(cfg_font["default-pallette"], new_config)
    new_config["fonts"] = fonts

    new_config["default_font"] = obj["default-font"]
    new_config["invalid_sha_responses"] = tuple(obj["invalid-sha-responses"])
    new_config["developers"] = tuple(obj["developers"])
    new_config["website_check_delay"] = obj["website-check-delay"]
    new_config["prefix"] = obj["prefix"]
    new_config["update_channel"] = obj["update-channel"]
    
    g_config = new_config

    if os.environ.get("token") is not None:
        return os.environ.get("token")
    elif os.path.isfile("./token"):
        with open("./token", "r") as f:
            return f.read()
    else:
        return obj["token"]

async def dl(msg, text: str, font=None, color_pallette=None):
    def draw_block(buffer, block_arr, block_offset, block_mask, color_pallette, offset):
        # Slice of image buffer that will be modified
        buffer_slice = buffer[offset[1]:(offset[1] + block_arr.shape[0]),
                              offset[0]:(offset[0] + block_arr.shape[1])];
        
        # Iterate all colors
        for color, color_mask in color_pallette:
            mask = color_mask & block_mask
            if mask != 0:
                buffer_slice[(block_arr & mask) != 0] = color # only draw where the font defines the drawn area
    
    begin = time.time()

    # chose font and color pallette
    if font is not None:
        if font in g_config["fonts"]:
            font = g_config["fonts"][font]
        else:
            color_pallette = resolve_pallette(font)
            if color_pallette is not None:
                color_pallette=font
                font=g_config["fonts"][g_config["default_font"]]
            else:
                await msg.send("Invalid font.")
                return
    else:
        font = g_config["fonts"][g_config["default_font"]]
    
    if color_pallette is not None:
        color_pallette = resolve_pallette(color_pallette)
        if color_pallette is None:
            await msg.send("Invalid color palette.")
            return
    else:
        color_pallette = font["default_pallette"]
    
    if "," in text:
        # asterisk encoding
        blocks = [[]]
        for blk in text.split(","):
            if blk == "":
                blocks.append([])
            else:
                blk_num_length = len([x.isdigit() for x in blk])
                blk_num = int(blk[:blk_num_length])
                blk_mod = blk[blk_num:]
                modif = 0
                if r"//" in blk_mod:
                    modif |= 256
                if r"\\" in blk_mod:
                    modif |= 512
                blocks[-1].append((blk_num | modif) * 0b100000000010000000001)
    else:
        blocks = []
        text = text.replace("//", " ")
        text = text.replace("/", "-")
        for column in text.split(" "):
            blocks.append([])
            for blk in column.split("-"):
                charmask = 0
                for g in blk:
                    charmask |= g_config["glyph_map"][g]
                blocks[-1].append(charmask)
    
    grid_dimensions = (len(blocks), max([len(i) for i in blocks]))
    
    block_offset = font["block_offset"]
    block_arr = font["arr"]
    img_size = [block_offset[i] * (grid_dimensions[i] - 1) + block_arr.shape[(i+1)%2] for i in (0,1)]
    
    # Allocate image buffer to draw on
    buffer = np.zeros(img_size[::-1], dtype=np.uint32)
    
    # Draw each block, column-by-column
    for column in range(len(blocks)):
        for row in range(len(blocks[column])):
            draw_block(buffer, block_arr, block_offset, blocks[column][row], color_pallette,
                      (column * block_offset[0], row * block_offset[1]))
    
    arr = io.BytesIO()
    Image.fromarray(buffer, "RGBA").save(arr, "png")
    arr.seek(0)
    
    await msg.send(f"responded in {(time.time() - begin):.3}s", file=discord.File(arr, "result.png"))

async def sha(msg, content, chain=None):
    link = f"https://doughbyte.com/art/?show={get_sha256(content)}"
    response = await g_session.get(link)
    page = await response.text()
    if response.status == 200 and get_sha256(page) not in g_config["invalid_sha_responses"]:
        if chain=="page":
            await msg.send(f"The sha of the previous page resulted in another page! {link}")
        elif chain=="image":
            await msg.send(f"The sha of the image on the previous page resulted in another page! {link}")
        else:
            await msg.send(f"GOOD {link}")
        await sha(msg, page, "page")
        png_image_fingerprint = "<img src=\'data:image/png;base64,"
        begin = page.find(png_image_fingerprint)
        if begin != -1:
            begin += len(png_image_fingerprint)
            end = page.find("'", begin)
            imgstring = page[begin:end]
            imgdata = base64.b64decode(imgstring)
            await sha(msg, imgdata, "image")

    elif not chain:
        await msg.send(f"BAD {response.status} {link}")

async def colors(msg):
    def color_hex(num):
        r, g, b = [(num >> i)&0xFF for i in(0,8,16)]
        return f"#{r:0{2}x}{g:0{2}x}{b:0{2}x}"
    
    response = "```Available colors:"
    cols = [n for n in g_config["modular_colors"]]
    
    for i in range(0, len(g_config["modular_colors"]), 4):
        response+=f"\n  {cols[i]} {cols[i+1]} {cols[i+2]} {cols[i+3]}"
    # draw a grid of available colors
    w, h = 40, 40
    img = Image.new("RGB", (w * 4, h * 4))
    imgd = ImageDraw.Draw(img)
    for x in range(4):
        for y in range(4):
            imgd.rectangle(((x*w, y*h), (x*w+w, y*h+h)), fill=color_hex(g_config["modular_colors"][cols[x + y * 4]]))
    
    arr = io.BytesIO()
    img.save(arr, "png")
    arr.seek(0)
    await msg.send(response + "```", file=discord.File(arr, "colors.png"))

class DoughClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.bg_task = self.loop.create_task(self.website_change_check())

    async def on_ready(self):
        global g_session
        g_session = aiohttp.ClientSession()
        async with g_session.get("https://doughbyte.com/art/") as response:
            if response.status != 200:
                print("could not connect to doughbyte")
            else:
                g_config["website_hash"] = get_sha256(await response.read())
        
        print(f"Logged in as {self.user.name} : {self.user.id}")

    async def website_change_check(self):
        await self.wait_until_ready()
        while not self.is_closed():
            if g_session is None:
                return
            async with g_session.get("https://doughbyte.com/art/") as response:
                if response.status != 200:
                    print("could not connect to doughbyte")
                else:
                    htmlhash = get_sha256(response.read())
                    if htmlhash != g_config["website_hash"]:
                        g_config["website_hash"] = htmlhash
                        channel = self.get_channel(g_config["update_channel"])
                        await channel.send("there was a change on the website! https://doughbyte.com/art/")
            
            delay = g_config["website_check_delay"]
            await asyncio.sleep(delay)
    
    async def on_message(self, message):
        if (not message.content) or (not message.content[0]==g_config["prefix"]):
            return
        words = message.content[1:].split(" ")
        authorized = message.author.id in g_config["developers"] # check for developer permissions
        argc = len(words) - 1
        
        if words[0]=="dl":
            if argc==1:
                await dl(message.channel, words[1])
            elif argc==2:
                await dl(message.channel, words[1], words[2])
            elif argc==3:
                await dl(message.channel, words[1], words[2], words[3])
            else:
                await message.channel.send("invalid arguments")
        
        elif words[0]=="sha" or words[0]=="sha256":
            if argc==0 and len(message.attachments)!=0:
                for a in message.attachments:
                    await sha(message.channel, a)
            elif argc==1:
                await sha(message.channel, words[1])
            else:
                await message.channel.send("invalid arguments")
        
        elif words[0]=="help":
            await message.channel.send('''```Commands:
  {p}dl message [font/color] [color] - draws bre-ish
  {p}sha message - calculates sha256 sum of the message
  {p}fonts - prints available fonts
  {p}colors - prints available colors
  {p}help - prints this information```'''.format(p=g_config["prefix"]))
        elif words[0]=="fonts":
            response = "```Available fonts:"
            for name in g_config["fonts"]:
                response += f"\n  {name}"
            await message.channel.send(response + "```")
        
        elif words[0]=="colors":
            await colors(message.channel)
        
        elif words[0]=="reload" and authorized:
            load_config()
       
        elif words[0]=="shutdown" and authorized:
            await self.close()
        
        elif words[0]=="printcfg" and authorized:
            def dumper(obj):
                try:
                    return obj.toJSON()
                except:
                    return "<unserializable object>"
            
            config = json.dumps(g_config, default=dumper, indent=4)
            arr = io.BytesIO()
            arr.write(config.encode("utf-8"))
            arr.seek(0)
            await message.channel.send(file=discord.File(arr, "config.json"))
        
        elif words[0]=="updatecfg" and authorized:
            if len(message.attachments)==1:
                config_url = message.attachments[0].url
                response = await g_session.get(config_url)
                r = await response.read()
                with open(f"./{message.attachments[0].filename}", "wb") as f:
                    f.write(r)
        
        else:
            await message.channel.send("invalid command")


if __name__ == "__main__":
    client = DoughClient()
    client.run(load_config())
