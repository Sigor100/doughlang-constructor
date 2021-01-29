import io
import os
import discord
from discord.ext import commands
import json
import hashlib
import requests
import time
import sys
from PIL import Image
import numpy as np


glyph_names = ()
glyph_map_userinput = {}
glyph_map_numbers = ()
fonts = {}
color_pallettes = {}
invalid_responses = ()
default_font = ""
developers = ()
dev_mode = None


def hex_to_color(hx, a = 255):
    if hx[:1] == "#":
        hx = hx[1:]
    r = int(hx[0:2], 16)
    g = int(hx[2:4], 16)
    b = int(hx[4:6], 16)
    if (len(hx) > 6):
        a = int(hx[6:8], 16)
    return (r, g, b, a)


def loadres(is_dev=None):
    global glyph_names
    global glyph_map_userinput
    global glyph_map_numbers
    global fonts
    global color_pallettes
    global invalid_responses
    global default_font
    global developers
    global dev_mode

    with open("./config.json", "r") as f:
        obj = json.load(f)
    
    glyph_names = tuple(obj["glyph-names"])

    color_pallettes = {}
    for name in obj["color-pallettes"]:
        pairs = [(hex_to_color(color), obj["color-pallettes"][name][color]) for color in obj["color-pallettes"][name]]
        color_pallettes[name] = tuple(pairs)

    fonts = {}
    for name in obj["fonts"]:
        fonts[name] = {}
        ldict = obj["fonts"][name]
        with open(ldict["source"], "rb") as f:
            fonts[name]["arr"] = np.load(f)
        fonts[name]["block_offset"] = ldict["block-offset"]
        fonts[name]["default_pallette"] = color_pallettes[ldict["default-pallette"]]

    
    glyph_map_numbers = []
    for i in range(0, 1024):
        glyph_map_numbers.append(0)
        for n in range(0, 10):
            mask = 0b100000000010000000001 << n
            if i & mask != 0:
                glyph_map_numbers[-1] |= mask
    glyph_map_numbers = tuple(glyph_map_numbers)
    
    glyph_map_userinput = {}
    for i in range(0, len(glyph_names)):
        bits = 0b100000000010000000001 << i
        glyph_map_userinput[glyph_names[i][:1].upper()] = bits
        glyph_map_userinput[glyph_names[i][:1].lower()] = bits
        glyph_map_userinput[str((i + 1) % 10)] = bits
    
    default_font = obj["default-font"]

    developers = tuple(obj["developers"])

    # variables used to configure discord.py
    botvars = {}
    invalid_responses = tuple(obj["invalid-responses"])

    if is_dev is not None:
        dev_mode = is_dev
        if is_dev:
            botvars_postfix = "-dev"
        else:
            botvars_postfix = ""

        for k in ("token", "description", "prefix"):
            botvars[k] = obj[k+botvars_postfix]
        
        if botvars["token"].startswith("load:"):
            with open(botvars["token"][5:], "r") as f:
                botvars["token"] = f.read()
        elif botvars["token"].startswith("getenv:"):
            botvars["token"] = os.getenv(botvars["token"][7:])
        return botvars


if __name__ == "__main__":
    global bot
    if "--dev" in sys.argv:
        print("starting in developer mode")
        botvars = loadres(True)
    else:
        botvars = loadres(False)
    bot = commands.Bot(command_prefix=botvars["prefix"], description=botvars["description"], intents=discord.Intents.default())

# commands

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')


@bot.check
async def dev_mode_check(ctx):
    if dev_mode and ctx.author.id not in developers:
        ctx.send("This is the dev bot. Use the regular bot instead.")
        return False
    else:
        return True


def makeimg(block_masks, font, color_pallette):
    def draw_block(font_mask, target_pixels, offset, mask, color): # todo: implement this in c++
        for i in range(font_mask.shape[0]):
            for j in range(font_mask.shape[1]):
                if mask & font_mask[i][j] != 0:
                    target_pixels[i + offset[0], j + offset[1]] = color
    
    block_grid_size = [1, 0]
    stack_size = 0
    for b in block_masks: # calculate the horizontal and vertical size
        if b == 0:
            block_grid_size[0] += 1
            block_grid_size[1] = max(block_grid_size[1], stack_size)
            stack_size = 0
        else:
            stack_size+=1
    block_grid_size[1] = max(block_grid_size[1], stack_size)
    
    result = Image.new("RGBA", # create the destination image
        [font["block_offset"][i]*(block_grid_size[i]-1)+font["arr"].shape[i] for i in(0,1)],
        (0, 0, 0, 0))
    result_pixels = result.load()

    block_grid_position = [0, 0]
    for char_mask in block_masks: # draw every block on the result image
        if char_mask == 0:
            block_grid_position[0] += 1
            block_grid_position[1] = 0
        else:
            for cpass in color_pallette:
                mask = char_mask & cpass[1]
                if mask == 0:
                    continue
                draw_block(font["arr"], result_pixels,
                [font["block_offset"][i]*block_grid_position[i] for i in(0,1)],
                mask, cpass[0])
            block_grid_position[1] += 1
    return result


@bot.command(description='makes a sentence')
async def dl(ctx, text: str, font=None, color_pallette=None):
    begin = time.time()

    if font is None:
        font = fonts[default_font]
    else:
        font = fonts[font]
    
    if color_pallette is not None:
        color_pallette = color_pallettes[color_pallette]
    else:
        color_pallette = font["default_pallette"]
    
    blocks = []
    if len(text.split("/")) >= len(text.split(",")):
        # normal mode
        for b in text.split("/"):
            if b == "":
                blocks.append(0)
            else:
                mask = 0
                for c in b:
                    mask |= glyph_map_userinput[c]
                blocks.append(mask)
    else:
        # asterisk encoding
        for b in text.split(','):
            if b == "":
                blocks.append(0)
            else:
                if b.endswith("//"):
                    if b.endswith("\\\\//"):
                        blocks.append(glyph_map_numbers[int(b[:-4]) + 768])
                    else:
                        blocks.append(glyph_map_numbers[int(b[:-2]) + 256])
                elif b.endswith("\\\\"):
                    if b.endswith("//\\\\"):
                        blocks.append(glyph_map_numbers[int(b[:-4]) + 768])
                    else:
                        blocks.append(glyph_map_numbers[int(b[:-2]) + 512])
                else: blocks.append(glyph_map_numbers[int(b)])
    print(blocks)
    arr = io.BytesIO()
    makeimg(blocks, font, color_pallette).save(arr, "png")
    arr.seek(0)
    await ctx.send(f"responded in {(time.time() - begin):.3}s", file=discord.File(arr, "result.png"))


@bot.command(description='calculates the sha256 hash of argument given')
async def sha(ctx, text: str):
    def get_hash(obj):
        return hashlib.sha256(obj).hexdigest()
    
    link = f"https://doughbyte.com/art/?show={get_hash(text.encode('utf-8'))}"
    try:
        response = requests.get(link)
        if response.status_code == 200 and get_hash(response.content) not in invalid_responses:
            response = "OK"
        else:
            response = "BAD {}".format(response.status_code)
    except requests.ConnectionError:
        response = "BAD (connection error)"
    
    await ctx.send("{response} {link}".format(response=response, link=link))


@bot.command()
async def dev(ctx, arg):
    if dev_mode:
        if arg == "reboot":
            await bot.close()
        elif arg == "reload":
            loadres()


if __name__ == "__main__":
    bot.run(botvars["token"])