import os
import discord
import yt_dlp as youtube_dl
import time
import datetime
import asyncio
import threading
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PREFIX = os.getenv('PREFIX')
KEY = os.getenv('GOOGLE_KEY')
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

intents = discord.Intents.all()

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')


@client.event
async def on_message(message):
    args = message.content[3:]
    if (message.author.id != client.application_id):
        cmd = message.content[:2]
        if (cmd == PREFIX + '?'):  # Help
            return await show_help(message)
        if (cmd == PREFIX + 'p'):  # Play
            return await add_song(message, args)
        if (cmd == PREFIX + 'q'):  # Queue
            return await view_queue(message)
        if (cmd == PREFIX + 's'):  # Skip
            return await skip_song(message)
        if (cmd == PREFIX + 'r'):  # Remove
            return await remove_song(message, args[0])
        if (cmd == PREFIX + 'm'):  # Move
            args = args.split(' ')
            if (args[0] == ''):
                return await message.channel.send('> Me tenes que decir que canción mover, imbécil')
            if (len(args) >= 2):
                return await move_song(message, args[0], args[1])
            elif (len(args) == 1):
                return await move_song(message, args[0])
        if (cmd == PREFIX + 'h'):  # Pause/Resume
            return await play_pause(message)


def get_service():
    return build("youtube", "v3", developerKey=KEY)


def search_yt(query):
    query = query.replace(' ', '%20')
    service = get_service()
    video_id = ''

    if ('www.youtube.com' in query):
        video_id = query.split('https://www.youtube.com/watch?v=')[1]
    elif ('youtu.be' in query):
        video_id = query.split('https://youtu.be/')[1].split('?')[0]
    else:
        video_id = service.search().list(
            part="id",
            q=query,
            safeSearch="none"
        ).execute()["items"][0]["id"]["videoId"]

    video = service.videos().list(
        part="contentDetails,snippet",
        id=video_id
    ).execute()
    duration = video["items"][0]["contentDetails"]["duration"]
    duration = duration[2:].split('H')
    rawDuration = 0
    prettyDuration = ''

    if (len(duration) > 1):
        if (int(duration[0]) < 10):
            duration[0] = '0' + duration[0]
        prettyDuration = duration[0] + ':'
        rawDuration += int(duration[0]) * 3600
        duration.pop(0)

    duration = duration[0].split('M')
    if (len(duration) > 1):
        if (int(duration[0]) < 10):
            duration[0] = '0' + duration[0]
        prettyDuration += duration[0] + ':'
        rawDuration += int(duration[0]) * 60
        duration.pop(0)
    else:
        prettyDuration += '00:'

    duration = duration[0].split('S')
    if (len(duration) > 1):
        if (int(duration[0]) < 10):
            duration[0] = '0' + duration[0]
        prettyDuration += duration[0]
        rawDuration += int(duration[0])
        duration.pop(0)

    return Song('https://www.youtube.com/watch?v=' + video_id, video["items"][0]["snippet"]["title"], prettyDuration,
                rawDuration)


async def show_help(message):
    embed = discord.Embed(color=discord.Colour.yellow())
    embed.title = 'Lista de comandos'
    embed.description = '<a> = Parametro obligatorio\n{a} = Parametro opcional'
    embed.add_field(name='k?', value='Muestra esta lista de comandos', inline=False)
    embed.add_field(name='kp <Link de youtube, o busqueda>', value='Reproduce un video de youtube', inline=False)
    embed.add_field(name='kq', value='Muestra la cola de audios que se van a reproducir', inline=False)
    embed.add_field(name='ks', value='Salta el audio que se este reproduciendo', inline=False)
    embed.add_field(name='kr <Indice>', value='Elimina un audio de la cola', inline=False)
    embed.add_field(name='km <Indice> {Objetivo}', value='Mueve un audio a la posición 1 o el objetivo', inline=False)
    embed.add_field(name='kh', value='Pausa o resume la reproducción de audio', inline=False)
    await message.channel.send(embed=embed)


global queue
queue = []
global voice_connection
voice_connection = None
global task


def view_queue(message):
    global queue
    if (len(queue) == 0):
        return message.reply('> La queue esta vacia')
    embed = discord.Embed(color=discord.Colour.blue())
    i = 0
    for item in queue:
        if (i < 25):
            if (i == 0):
                embed.add_field(name=f'▶️ {item.title}', value=item.duration, inline=False)
            else:
                embed.add_field(name=f'{i}. {item.title}', value=item.duration, inline=False)
            i += 1
    return message.channel.send(embed=embed)


async def add_song(message, args):
    if (message.author.voice.channel == None):
        return await message.reply('> Tenes que estar en un voice chat')
    else:
        global queue
        if (len(queue) == 25):
            return message.channel.send('> ⛔ La queue esta llena ⛔')

        global voice_connection
        voice_clients = client.voice_clients
        if (len(voice_clients) > 0):
            voice_connection = voice_clients[0]
        else:
            vc = message.author.voice.channel
            voice_connection = await vc.connect()

        songData = search_yt(args);
        queue.append(songData)
        if (len(queue) == 1 and voice_connection.is_playing() == False):
            await play_song(message)
        else:
            await message.channel.send(f'> Agregando: `{songData.title}` a la queue')


def play_next(message):
    global queue
    if (len(queue) > 0):
        del queue[0]
        if (len(queue) > 0):
            global voice_connection
            file = asyncio.run_coroutine_threadsafe(YTDLSource.from_url(queue[0].id, loop=client.loop, stream=True),
                                                    loop=client.loop).result()
            voice_connection.play(file, after=lambda e: play_next(message))


async def play_song(message):
    global queue
    if (len(queue) == 0):
        return
    asyncio.run_coroutine_threadsafe(message.reply(f'> Reproduciendo: `{queue[0].title}`'), loop=client.loop)
    file = await YTDLSource.from_url(queue[0].id, loop=client.loop, stream=True)
    voice_connection.play(file, after=lambda e: play_next(message))


async def skip_song(message):
    if (message.author.voice.channel == None):
        return await message.reply('> Tenes que estar en un voice chat')
    if (len(queue) > 0):
        global voice_connection
        await message.reply(f'> Saltando la canción: `{queue[0].title}`')
        del queue[0]
        voice_connection.stop()
        if (len(queue) > 0):
            await play_song(message)
    else:
        await message.reply('> La queue esta vacia')


async def remove_song(message, index):
    if (message.author.voice.channel == None):
        return await message.reply('> Tenes que estar en un voice chat')
    global queue
    if (len(queue) < 1):
        return await message.reply('> La queue esta vacia')

    index = int(index)
    if (index < 1):
        return await message.reply('> El indice tiene que ser mayor a 0')
    if (index > 25):
        return await message.reply('> El indice tiene que ser menor a 25')
    if (len(queue) < index):
        return await message.reply('> Ese indice no existe en la queue')

    await message.reply(f'> Eliminando el audio {queue[index].title} de la queue')
    queue.pop(index)


async def move_song(message, start, target=None):
    if (message.author.voice.channel == None):
        return await message.reply('> Tenes que estar en un voice chat')
    global queue
    if (len(queue) < 1):
        return await message.reply('> La queue esta vacia')

    start = int(start)
    if (start < 1):
        return await message.reply('> El indice tiene que ser mayor a 0')
    if (start > 25):
        return await message.reply('> El indice tiene que ser menor a 25')
    if (len(queue) < start):
        return await message.reply('> Ese indice no existe en la queue')

    song = queue[start]
    queue.pop(start)

    if (target != None):
        target = int(target)
        if (target < 1):
            return await message.reply('> El indice tiene que ser mayor a 0')
        if (target > 25):
            return await message.reply('> El indice tiene que ser menor a 25')
        if (len(queue) < target):
            return await message.reply('> Ese indice no existe en la queue')
        queue.insert(target, song)
        return await message.reply(f'> Moviendo la canción {song.title} a la posición {target}')
    else:
        queue.insert(1, song)
        return await message.reply(f'> Moviendo la canción {song.title} al primer lugar')


async def play_pause(message):
    if (message.author.voice.channel == None):
        return await message.reply('> Tenes que estar en un voice chat')
    global voice_connection
    if (voice_connection != None):
        if (voice_connection.is_playing()):
            voice_connection.pause()
            return await message.channel.send('> ⏸️ Pausando el temon ⏸️')
        else:
            voice_connection.resume()
            return await message.channel.send('> ▶️ Resumiendo la bailanta ▶️')


youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = ""

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)


class Song:
    def __init__(self, id, title, duration, rawDuration):
        self.id = id
        self.title = title
        self.duration = duration
        self.rawDuration = rawDuration


client.run(TOKEN)
