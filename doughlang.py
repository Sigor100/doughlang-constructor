import io
from PIL import Image
import PIL.ImageOps
import os
import discord
from discord.ext import commands
import json
import numpy as np
import hashlib
import requests

intents = discord.Intents.default()

bot = commands.Bot(command_prefix='?', description='''This bot can write doughlang''', intents=intents)

glyph_names = ()
glyph_map_userinput = {}
glyph_map_numbers = ()
fonts = {}
color_pallets = {}
invalid_responses = ()

def loadres():
    global glyph_names
    global glyph_map_userinput
    global glyph_map_numbers
    global fonts
    global color_pallets
    global invalid_responses

    with open("./config.json", "r") as f:
        obj = json.load(f)
    
    glyph_names = tuple(obj["glyph-names"])

    color_pallets = {}
    for name in obj["color-pallets"]:
        pairs = [(resolve_color(color), obj["color-pallets"][name][color]) for color in obj["color-pallets"][name]]
        color_pallets[name] = tuple(pairs)

    fonts = {}
    for name in obj["fonts"]:
        fonts[name] = {}
        ldict = obj["fonts"][name]
        with open(ldict["source"], "rb") as f:
            fonts[name]["arr"] = np.load(f)
        fonts[name]["block_offset"] = ldict["block-offset"]
        fonts[name]["default_pallet"] = color_pallets[ldict["default-pallet"]]

    with open(obj["binary-lookup"], "r") as f:
        glyph_map_numbers = tuple(f.read().split("\n"))
    
    glyph_map_userinput = {}
    for i in range(0, len(glyph_names)):
        bits = 0b100000000010000000001 << i
        glyph_map_userinput[glyph_names[i][:1].upper()] = bits
        glyph_map_userinput[glyph_names[i][:1].lower()] = bits
        glyph_map_userinput[str(i + 1)] = bits
    
    invalid_responses = tuple(obj["invalid-responses"])

    if obj["token"] == "":
        print("you need to add your bot token to config.json")
        exit()
    else:
        return obj["token"]

def makeimg(block_masks, font, color_pallet):
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
            for cpass in color_pallet:
                mask = char_mask & cpass[1]
                if mask == 0:
                    continue
                draw_block(font["arr"], result_pixels,
                [font["block_offset"][i]*block_grid_position[i] for i in(0,1)],
                mask, cpass[0])
            block_grid_position[1] += 1
    return result

def resolve_color(hx, a = 255):
    if hx[:1] == "#":
        hx = hx[1:]
    r = int(hx[0:2], 16)
    g = int(hx[2:4], 16)
    b = int(hx[4:6], 16)
    if (len(hx) > 6):
        a = int(hx[6:8], 16)
    return (r, g, b, a)

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.command(description='makes a sentence')
async def dl(ctx, text: str, font="king", color_pallet=None):
    blocks = []
    for b in text.split("/"):
        if b == "":
            blocks.append(0)
        else:
            mask = 0
            for c in b:
                mask |= glyph_map_userinput[c]
            blocks.append(mask)

    if color_pallet is not None:
        pallet = color_pallets[color_pallet]
    else:
        pallet = fonts[font]["default_pallet"]
    
    arr = io.BytesIO()
    makeimg(blocks, fonts[font], pallet).save(arr, "png")
    arr.seek(0)
    await ctx.send(file=discord.File(arr, "result.png"))

@bot.command(description='makes a sentence asterisk syntax style')
async def dla(ctx, text: str, font="king", color_pallet=None):
    # simply convert to the other format
    blocks = []
    for b in text.split(','):
        if b == "":
            blocks.append("")
        else:
            if b.endswith("//"):
                if b.endswith("\\\\//"):
                    blocks.append(bitwise_to_letters[int(b[:-4]) + 768])
                else:
                    blocks.append(bitwise_to_letters[int(b[:-2]) + 256])
            elif b.endswith("\\\\"):
                if b.endswith("//\\\\"):
                    blocks.append(bitwise_to_letters[int(b[:-4]) + 768])
                else:
                    blocks.append(bitwise_to_letters[int(b[:-2]) + 512])
            else: blocks.append(bitwise_to_letters[int(b)])
    
    if color_pallet is not None:
        pallet = color_pallets[color_pallet]
    else:
        pallet = fonts[font]["default_pallet"]
    
    arr = io.BytesIO()
    makeimg(blocks, fonts[font], pallet).save(arr, "png")
    arr.seek(0)
    await ctx.send(file=discord.File(arr, "result.png"))

@bot.command(description='makes a sentence')
async def sha(ctx, text: str):
    link = "https://doughbyte.com/art/?show={hash}".format(hash=hashlib.sha256(text.encode('utf-8')).hexdigest())
    try:
        response = requests.get(link)
        if response.status_code == 200:
            response_hash = hashlib.sha256(response.content).hexdigest()
            print(response_hash)
            for invalid_hash in invalid_responses:
                if response_hash == invalid_hash:
                    response = "BAD"
                    break
        else:
            response = "BAD"
        
    except requests.ConnectionError:
        response = "BAD"
    
    if response != "BAD":
        response = "OK"
    await ctx.send("{response} {link}".format(response=response, link=link))

@bot.command(description='ping the bot')
async def ping(ctx):
    await ctx.send("pong")

@bot.command(description='dev command')
async def reload(ctx):
    loadres()
    await ctx.send("reload complete")

if __name__ == "__main__":
    bot.run(loadres())