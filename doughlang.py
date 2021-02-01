import io
import os
import discord
from discord.ext import commands
import json
import hashlib
import requests
import time
import sys
from PIL import Image, ImageDraw
import numpy as np
import aiohttp
import asyncio


glyph_map = {}
modular_colors = {}
color_pallettes = {}
fonts = {}
default_font = ""
invalid_sha_responses = ()
developers = ()
dev_mode = None


def hex_to_color(hx): # returns the color of "#rrggbb" in uint32 form
    r = int(hx[1:3], 16)
    g = int(hx[3:5], 16)
    b = int(hx[5:7], 16)
    return r + (g << 8) + (b << 16) + 0xFF000000

def resolve_pallette(name):
    if name in color_pallettes:
        return color_pallettes[name]
    elif len(name.split("-")) == 2:
        c1, c2 = name.split("-")
        if c1 in modular_colors and c2 in modular_colors:
            return ((modular_colors[c2], 0x300c0300), (modular_colors[c1], 0xff3fcff))
    elif name in modular_colors:
        return ((modular_colors[name], 0x3fffffff),)
    return None

def draw_block(buffer, block_arr, block_offset, block, color_pallette, offset):

    # Slice of image buffer that will be modified
    buffer_slice = buffer[offset[1]:(offset[1] + block_arr.shape[0]),
                          offset[0]:(offset[0] + block_arr.shape[1])];
    
    # Iterate all colors
    for color, mask in color_pallette:
        # background mask. True for background, False for already drawn
        background = buffer_slice == 0
        
        toDraw = ((block_arr
                   * background # Draw only on background
                   & block      # draw specified symbols only
                   & mask       # draw color pallette's symbols only
                   ) != 0).astype(np.uint32)
        buffer_slice += toDraw * color

def loadres(is_dev=None):
    global glyph_map
    global modular_colors
    global color_pallettes
    global fonts
    global default_font
    global invalid_sha_responses
    global developers
    global dev_mode

    with open("./config.json", "r") as f:
        obj = json.load(f)
    
    glyph_map = {}
    for mapping in obj["glyph-mapping"]:
        for i in range(10):
            bits = 0b100000000010000000001 << i
            glyph_map[mapping[i]] = bits


    modular_colors = {}
    for name in obj["modular-colors"]:
        modular_colors[name] = hex_to_color(obj["modular-colors"][name])
    
    color_pallettes = {}
    for name in obj["color-pallettes"]:
        color_pallettes[name] = tuple((hex_to_color(color_key), obj["color-pallettes"][name][color_key]) for color_key in obj["color-pallettes"][name])[::-1]

    fonts = {}
    for name in obj["fonts"]:
        fonts[name] = {}
        cfg_font = obj["fonts"][name]
        with open(cfg_font["source"], "rb") as f:
            fonts[name]["arr"] = np.copy(np.swapaxes(np.load(f), 0, 1))
        fonts[name]["block_offset"] = cfg_font["block-offset"]
        fonts[name]["default_pallette"] = resolve_pallette(cfg_font["default-pallette"])

    default_font = obj["default-font"]
    invalid_sha_responses = tuple(obj["invalid-sha-responses"])
    developers = tuple(obj["developers"])

    # variables used to configure discord.py
    if is_dev is not None:
        botvars = {}

        dev_mode = is_dev
        if is_dev:
            botvars_postfix = "-dev"
        else:
            botvars_postfix = ""

        botvars["description"]=obj["description"+botvars_postfix]
        botvars["prefix"]=obj["prefix"+botvars_postfix]
        token_field=obj["token"+botvars_postfix]
        
        if os.environ.get("token") is not None:
            botvars["token"] = os.environ.get("token")
        elif os.path.isfile(token_field):
            with open(token_field, "r") as f:
                botvars["token"] = f.read()
        else:
            botvars["token"] = token_field
        return botvars


if __name__ == "__main__":
    botvars = loadres("--dev" in sys.argv)
    bot = commands.Bot(command_prefix=botvars["prefix"], description=botvars["description"], intents=discord.Intents.default())

# commands

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} : {bot.user.id}")


@bot.check
async def dev_mode_check(ctx):
    return not dev_mode or ctx.author.id in developers

@bot.command(description='makes a sentence')
async def dl(ctx, text: str, font=None, color_pallette=None):
    begin = time.time()

    # chose font and color pallette
    if font is not None:
        if font in fonts:
            font = fonts[font]
        else:
            color_pallette = resolve_pallette(font)
            if color_pallette is not None:
                color_pallette=font
                font=fonts[default_font]
            else:
                await ctx.send("Invalid font.")
                return
    else:
        font = fonts[default_font]
    
    if color_pallette is not None:
        color_pallette = resolve_pallette(color_pallette)
        if color_pallette is None:
            await ctx.send("Invalid color palette.")
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
                if "//" in blk_mod:
                    modif |= 256
                if "\\\\" in blk_mod:
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
                    charmask |= glyph_map[g]
                blocks[-1].append(charmask)
    
    grid_dimensions = (len(blocks), max([len(i) for i in blocks]))
    
    block_offset = font["block_offset"]
    block_arr = font["arr"]
    img_size = [block_offset[i] * (grid_dimensions[i] - 1) + block_arr.shape[(i+1)%2] for i in (0,1)]
    
    # Allocate image buffer to draw on
    buffer = np.zeros(img_size[::-1], dtype=np.uint32);
    
    # Draw each block, column-by-column
    for column in range(len(blocks)):
        for row in range(len(blocks[column])):
            draw_block(buffer, block_arr, block_offset, blocks[column][row], color_pallette,
                       (column * block_offset[0], row * block_offset[1]))
    
    arr = io.BytesIO()
    Image.fromarray(buffer, "RGBA").save(arr, "png")
    arr.seek(0)
    
    await ctx.send(f"responded in {(time.time() - begin):.3}s", file=discord.File(arr, "result.png"))


@bot.command(description='calculates the sha256 hash of argument given')
async def sha(ctx, text: str):
    def get_hash(string):
        return hashlib.sha256(string.encode('utf-8')).hexdigest()
    
    link = f"https://doughbyte.com/art/?show={get_hash(text)}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(link) as response:
            html = await response.text()
            if response.status == 200 and get_hash(html) not in invalid_sha_responses:
                response = "OK"
            else:
                response = f"BAD {response.status}"
    
    await ctx.send(f"{response} {link}")


@bot.command(name="fonts")
async def _fonts(ctx):
    response = "```Available fonts:"
    for name in fonts:
        response += f"\n{name}"
    await ctx.send(response + "```")

@bot.command()
async def colors(ctx):
    def color_hex(num):
        r, g, b = [(num >> i)&0xFF for i in(0,8,16)]
        return f"#{r:0{2}x}{g:0{2}x}{b:0{2}x}"
    
    response = "```Available colors:"
    cols = [n for n in modular_colors]
    
    for i in range(0, len(modular_colors), 4):
        response+=f"\n{cols[i]} {cols[i+1]} {cols[i+2]} {cols[i+3]}"
    # draw a grid of available colors
    w, h = 40, 40
    img = Image.new("RGB", (w * 4, h * 4))
    imgd = ImageDraw.Draw(img)
    for x in range(4):
        for y in range(4):
            imgd.rectangle(((x*w, y*h), (x*w+w, y*h+h)), fill=color_hex(modular_colors[cols[x + y * 4]]))
    
    arr = io.BytesIO()
    img.save(arr, "png")
    arr.seek(0)
    await ctx.send(response + "```", file=discord.File(arr, "colors.png"))


@bot.command()
async def dev(ctx, arg):
    if ctx.author.id in developers:
        if arg == "shutdown":
            await bot.close()
        elif arg == "reload":
            loadres()


if __name__ == "__main__":
    bot.run(botvars["token"])
