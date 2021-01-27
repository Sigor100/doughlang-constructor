import io
from PIL import Image
import PIL.ImageOps
import os
import discord
from discord.ext import commands

intents = discord.Intents.default()

bot = commands.Bot(command_prefix='?', description='''This bot can write doughlang''', intents=intents)

glyphs = (
    { "name":"Augustus", "offset":(0, 0) },
    { "name":"Tiberius", "offset":(0, 0) },
    { "name":"Gaius", "offset":(0, 0) },
    { "name":"Claudius", "offset":(72, 0) },
    { "name":"Nero", "offset":(72, 0) },
    { "name":"Bob", "offset":(144, 0) },
    { "name":"Otho", "offset":(0, 0) },
    { "name":"Vitellius", "offset":(0, 0) },
    { "name":"Hadrian", "offset":(0, 0) },
    { "name":"Domitian", "offset":(72, 0) },
)
glyphmap = {}
def_color_glyph = "888888"
def_color_special = "#cc1111"
def_color_backg = "#00000000"
bitwise_to_letters = ()

def resolve_color(hx, a = 255):
    if hx[:1] == "#":
        hx = hx[1:]
    r = int(hx[0:2], 16)
    g = int(hx[2:4], 16)
    b = int(hx[4:6], 16)
    if (len(hx) > 6):
        a = int(hx[6:8], 16)
    return (r, g, b, a)

def makeimg(blocks, color_glyph, color_special, color_backg):
    block_count = [1, 0]
    block_offset = (240, 100) # defined experimentally pretty much
    padding = (10, 10)

    stack_size = 0
    for b in blocks:
        if b == "": # double slash xxx//yyy -> "xxx", "", "yyy"  
            block_count[0] += 1
            block_count[1] = max(block_count[1], stack_size)
            stack_size = 0
        else:
            stack_size+=1
    block_count[1] = max(block_count[1], stack_size)

    result = Image.new("RGBA",
        (padding[0] + block_count[0] * block_offset[0] + 3,
        padding[1] + block_count[1] * block_offset[1] + 55), color_backg)
    
    colored_img = [g["img"] for g in glyphs]
    for n in range(0, len(colored_img)):
        pixels = colored_img[n].load()
        for i in range(colored_img[n].size[0]): # for every pixel in every image
            for j in range(colored_img[n].size[1]):
                if pixels[i,j][3] == 255: # if the pixel is opaque, change it to color_glyph
                    pixels[i,j] = color_glyph if n < 8 else color_special
    
    offset = list(padding)
    for b in blocks:
        if b == "": # double slash xxx//yyy -> "xxx", "", "yyy" 
            offset[0] += block_offset[0]
            offset[1] = padding[0]
        else:
            for c in b:
                glyph = glyphs[glyphmap[c]]
                result.paste(glyph["img"], 
                    (offset[0] + glyph["offset"][0],
                    offset[1] + glyph["offset"][1]),
                    mask=glyph["img"])
            offset[1] += block_offset[1]
    
    arr = io.BytesIO()
    result.save(arr, "png")
    arr.seek(0)
    return discord.File(arr, "result.png")

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.command(description='makes a sentence')
async def dl(ctx, text: str, color_glyph=def_color_glyph, color_special=def_color_special, color_backg=def_color_backg):
    if text == "e" or text == "E":
        await ctx.send("https://i.kym-cdn.com/photos/images/newsfeed/001/365/818/183.jpg")
    else:
        await ctx.send(file=makeimg(text.split('/'), resolve_color(color_glyph), resolve_color(color_special), resolve_color(color_backg)))

@bot.command(description='makes a sentence asterisk syntax style')
async def dla(ctx, text: str, color_glyph=def_color_glyph, color_special=def_color_special, color_backg=def_color_backg):
    # simply convert to the other format
    blocks = ["" if b == "" else bitwise_to_letters[int(b)] for b in text.split(',')]
    await ctx.send(file=makeimg(blocks, resolve_color(color_glyph), resolve_color(color_special), resolve_color(color_backg)))

if __name__ == "__main__":
    charset = Image.open("./charset.png")
    _, height = charset.size
    for i in range(0, len(glyphs)):
        glyphs[i]["img"] = charset.crop((i * height, 0, i * height + height, height))
    charset = None

    for i in range(0, len(glyphs)):
        glyphmap[glyphs[i]["name"][:1].upper()] = i
        glyphmap[glyphs[i]["name"][:1].lower()] = i
        glyphmap[str(i + 1)] = i # yes this is dumb

    with open("./lookup", "r") as f:
        bitwise_to_letters = tuple(f.read().split("\n"))

    with open("./token", "r") as f:
        token = f.read()
    bot.run(token)