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
import aiohttp
import asyncio


glyph_names = ()
glyph_map_text = {}
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
    return r + (g << 8) + (b << 16) + (a << 24)


def loadres(is_dev=None):
    global glyph_names
    global glyph_map_text
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
            fonts[name]["arr"] = np.copy(np.swapaxes(np.load(f), 0, 1))
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
    
    glyph_map_text = {}
    for i in range(0, len(glyph_names)):
        bits = 0b100000000010000000001 << i
        glyph_map_text[glyph_names[i][:1].upper()] = bits
        glyph_map_text[str((i + 1) % 10)] = bits
    
    for i in range(0, len(obj["bread-names"])):
        bits = 0b100000000010000000001 << i
        glyph_map_text[obj["bread-names"][i].lower()] = bits

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


class DrawIterator:
    def __init__(self, blocks, fontarr, color_pallette, canvas_size, block_size, block_offset):
        self.blocks = blocks
        self.fontarr = fontarr
        self.color_pallette = color_pallette
        self.canvas_size = canvas_size
        self.block_size = block_size
        self.block_offset = block_offset
        self.up_pass = []
        self.down_pass = []
        self.row = 0

    def __iter__(self):
        return self
    
    def __next__(self):
        if self.row == self.canvas_size[1]:
            raise StopIteration
        else:
            j = int(self.row / self.block_offset[1])
            if self.row % self.block_offset[1] == self.block_size[1] - self.block_offset[1]:
                self.up_pass = []
                
            elif self.row % self.block_offset[1] == 0:
                self.up_pass = self.down_pass
                # generate new down_pass
                self.down_pass = []
                for col in self.blocks:
                    if len(col) > j:
                        npass = []
                        for _, cmask in self.color_pallette:
                            mask = cmask & col[j]
                            if mask != 0:
                                npass.append(mask)
                        if len(npass) > 0:
                            self.down_pass.append(npass)
                    else:
                        self.down_pass.append([])
            
            buffer = np.zeros(self.canvas_size[0], np.uint32)
            passes = self.down_pass
            for passes in ((self.down_pass, 0), (self.up_pass, self.block_offset[1])):
                for i in range(len(passes[0])): # i is the current column
                    for mask in passes[0][i]:
                        startx = i*self.block_offset[0]
                        endx = startx + self.fontarr.shape[1]
                        buffer[startx:endx] |= self.fontarr[(self.row % self.block_offset[1]) + passes[1]] & mask
            
            result = np.zeros(buffer.size, dtype=np.uint32)
            for color, mask in self.color_pallette:
                temp = (buffer & mask)
                temp[temp!=0] = color
                result |= temp

            self.row+=1
            return result


@bot.command(description='makes a sentence')
async def dl(ctx, text: str, font=None, color_pallette=None):
    begin = time.time()

    # chose font and color pallette
    if font is None:
        font = fonts[default_font]
    else:
        font = fonts[font]
    if color_pallette is not None:
        color_pallette = color_pallettes[color_pallette]
    else:
        color_pallette = font["default_pallette"]
    
    print(len(glyph_map_numbers))
    if "," in text:
        # asterisk encoding
        blocks = [[]]
        for blk in text.split(","):
            if blk == "":
                blocks.append([])
            else:
                modif = 0
                newl = len(blk)
                if blk.endswith("//"):
                    modif += 256
                    newl = -2
                    if blk.endswith("\\\\//"):
                        modif += 512
                        newl = -4
                elif blk.endswith("\\"):
                    modif += 512
                    newl = -2
                    if blk.endswith("//\\\\"):
                        modif += 256
                        newl = -4
                print(modif)
                blocks[-1].append(glyph_map_numbers[int(blk[:newl]) + modif])
    else:
        blocks = []
        text = text.replace("//", " ")
        text = text.replace("/", "-")
        for column in text.split(" "):
            blocks.append([])
            for blk in column.split("-"):
                charmask = 0
                for g in blk:
                    charmask |= glyph_map_text[g]
                blocks[-1].append(charmask)
    
    grid_dimensions = (len(blocks), max([len(i) for i in blocks]))
    
    real_shape = [font["arr"].shape[(i+1)%2] for i in (0,1)]
    img_size = [font["block_offset"][i] * (grid_dimensions[i] - 1) + real_shape[i] for i in (0,1)]

    row_iterator = DrawIterator(blocks, font["arr"], color_pallette, img_size, real_shape, font["block_offset"])
    arr = io.BytesIO()
    Image.fromarray(np.vstack(tuple(row_iterator)), "RGBA").save(arr, "png")
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
            if response.status == 200 and get_hash(html) not in invalid_responses:
                response = "OK"
            else:
                response = f"BAD {response.status}"
    
    await ctx.send(f"{response} {link}")


@bot.command()
async def dev(ctx, arg):
    if ctx.author.id in developers:
        if arg == "shutdown":
            await bot.close()
        elif arg == "reload":
            loadres()


if __name__ == "__main__":
    bot.run(botvars["token"])