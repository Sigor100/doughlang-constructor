import io
from PIL import Image
import PIL.ImageOps
import os
import discord
from discord.ext import commands

description = '''This bot can write doughlang'''

intents = discord.Intents.default()

bot = commands.Bot(command_prefix='?', description=description, intents=intents)

glyphs = (
        { "name":"Augustus", "offset":(2, 10) },
        { "name":"Tiberius", "offset":(27, 3) },
        { "name":"Gaius", "offset":(11, 17) },
        { "name":"Claudius", "offset":(45, 0) },
        { "name":"Nero", "offset":(42, 18) },
        { "name":"Bob", "offset":(57, 15) },
        { "name":"Otho", "offset":(0, 32) },
        { "name":"Vitellius", "offset":(26, 27) },
        { "name":"Hadrian", "offset":(0, 11) },
        { "name":"Domitian", "offset":(26, 27) },
    )
glyphmap = {}
defglyphc = (180, 196, 104)
defbackc = (0, 0, 0, 0)

def makeimg(text:str, glyphc, backc):
    blocks = text.split('/')
    
    text_size = [1, 0]
    block_offset = (90,  38)
    streak = 0
    for b in blocks:
        if b == "":
            text_size[0] += 1
            text_size[1] = max(text_size[1], streak)
            streak = 0
        else:
            streak+=1
    text_size[1] = max(text_size[1], streak)

    result = Image.new("RGBA", (10 + text_size[0] * block_offset[0], 30 + text_size[1] * block_offset[1]), backc)
    
    offset = [2, 0]
    cimg = [g["img"] for g in glyphs]
    for n in cimg:
        pixels = n.load()
        for i in range(n.size[0]): # for every pixel
            for j in range(n.size[1]):
                if pixels[i,j][3] == 255:
                    pixels[i,j] = glyphc
    for b in blocks:
        if b == "":
            offset[0] += block_offset[0]
            offset[1] = 0
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
async def dl(ctx, text: str, r=defglyphc[0], g=defglyphc[1], b=defglyphc[2]):
    await ctx.send(file=makeimg(text, (r, g, b, 255), defbackc))

@bot.command(description='makes a sentence asterisk syntax style')
async def dla(ctx, text: str, r=defglyphc[0], g=defglyphc[1], b=defglyphc[2]):
    # simply convert to the other format
    blocks = text.split(',')
    new_text = ""
    for b in blocks:
        if b != "":
            number = int(b) # yes this is bad
            mask = 1
            for i in range(0,8):
                if (mask & number) != 0:
                    new_text += glyphs[i]["name"][:1]
                mask = mask << 1
        new_text += "/"

    await ctx.send(file=makeimg(new_text[:-1], defglyphc, defbackc))

# administrative command, pls don't use in the server or I'll have to implement permissions
@bot.command(description='really just quits. a shell script handles starting the bot again')
async def reboot(ctx):
    print("shutting down")
    await bot.close()

if __name__ == "__main__":
    charset = Image.open("./charset.png")
    _, height = charset.size
    for i in range(0, len(glyphs)):
        glyphs[i]["img"] = charset.crop((i * 36, 0, i * 36 + 36, height))
    charset = None

    for i in range(0, len(glyphs)):
        glyphmap[glyphs[i]["name"][:1].upper()] = i
        glyphmap[glyphs[i]["name"][:1].lower()] = i
        glyphmap[str(i + 1)] = i # yes this is dumb

    with open("./token", "r") as f:
        token = f.read()
    bot.run(token)