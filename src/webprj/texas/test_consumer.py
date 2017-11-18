from channels import Group
import json
from channels.sessions import channel_session
import random
from channels.auth import http_session_user, channel_session_user, channel_session_user_from_http
from django.db import transaction

from texas.models import *
from texas.views import *
from . import test_compare, desk_manipulation

from django.db import models
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse

#global public name
public_name = 'desk0'

# an global private group name array for each player
private_group = ['1', '2', '3', '4', '5', '6', '7', '8', '9']


@transaction.atomic
@channel_session_user
def diconnect_user(message, username):
    print('disconnect!')
    # Disconnect
    print(username)
    # get desk
    desk = Desk_info.objects.get(desk_name='desk0')
    max_capacity = desk.capacity
    #Group(public_name).discard(message.reply_channel)
    print('success')
    desk.current_capacity += 1

    # decide is_start
    if desk.current_capacity >= desk.capacity - 1:
        desk.is_start = False

    # decide owner
    this_user_info = User_info.objects.get(user=message.user)
    this_player = User_Game_play.objects.get(user=this_user_info)
    if desk.owner == this_user_info:
        players = User_Game_play.objects.filter(desk=desk)
        print(players)
        if len(players) == 1:
            # if this is the last user, desk.owner = None
            desk.owner = None
        else:
            # if still have people in the current desk, give the owner to him
            for player in players:
                if player != this_player:
                    desk.owner = player.user
                    break

    # retrieve position queue
    desk.position_queue += str(this_player.position)
    print("after leave: ", desk)

    # If current player is 1, owner can not start the game
    if desk.current_capacity == max_capacity - 1:
        content = {'can_start': 'no'}
        this_player = User_Game_play.objects.get(user=desk.owner)
        print(this_player.position)
        Group(str(this_player.position)).send({'text': json.dumps(content)})

    # delete User_Game_play
    User_Game_play.objects.get(user=this_user_info).delete()
    Group(desk.desk_name).discard(message.reply_channel)

    desk.save()
    return


@transaction.atomic
@channel_session_user
def start_logic(message):
    print('start signal received!')
    #TODO: let the owner be the dealer
    #arrange dealer
    cur_desk = Desk_info.objects.get(desk_name='desk0')
    users_of_cur_desk = User_Game_play.objects.filter(desk='desk0')
    active_users_queue = ''
    for user in users_of_cur_desk:
        active_users_queue += str(user.position)
    cur_desk.player_queue = active_users_queue
    # the first person in the queue is initialized as dealer
    dealer = User_Game_play.objects.get(desk='desk0',
                                        position=int(cur_desk.player_queue[0]))
    #TODO: let the next two player be blinds
    #arrange blind
    next_pos_in_queue = get_next_pos(0, len(users_of_cur_desk))
    small_blind = User_Game_play.objects.get(desk='desk0', position=int(cur_desk.player_queue[next_pos_in_queue]))
    next_pos_in_queue = get_next_pos(next_pos_in_queue, len(users_of_cur_desk))
    big_blind = User_Game_play.objects.get(desk='desk0', position=int(cur_desk.player_queue[next_pos_in_queue]))
    # the person move next is the next position of big_blind
    cur_desk.player_queue_pointer = get_next_pos(big_blind.position, len(users_of_cur_desk))
    #TODO: give every users 2 cards
    #arrange card
    cards = test_compare.shuffle_card(len(users_of_cur_desk))
    # first 5 random cards give desk
    desk_cards = ''
    for card in cards[:5]:
        desk_cards += str(card) + ' '
    desk_cards = desk_cards[:-1] # delete the last space character
    cur_desk.five_cards_of_desk = desk_cards
    Group(cur_desk.desk_name).send({'desk_cards': cur_desk.five_cards_of_desk})
    # giver each users his cards and store it in the User_Game_play
    start_index = 5
    for user in users_of_cur_desk:
        cur_user_cards = ''
        for card in cards[start_index: start_index + 2]:
            cur_user_cards += str(card) + ' '
        cur_user_cards = cur_user_cards[:-1]
        start_index += 2
        user.user_cards = cur_user_cards

    for user in users_of_cur_desk:
        Group(user.position).send({'user_cards': user.user_cards})
    # tell the public channel, who is dealer, who is big blind, who is small blind
    Group(cur_desk.desk_name).send({'dealer':[dealer.user.user.username, dealer.position],
                                    'big_blind': [big_blind.user.user.username, big_blind.position],
                                    'small_blind': [small_blind.user.user.username, small_blind.position]})


# player_queue is a cyclic queue, the next pos of the last pos is 0
def get_next_pos(cur_pos, len_queue):
    if cur_pos <= len_queue - 2:
        return cur_pos + 1
    return 0

@transaction.atomic
@channel_session_user
def ws_msg(message):
    # print(message['text'])
    try:
        data = json.loads(message['text'])
    except:
        return
    print(data)

    # The player click leave room
    if 'command' in data:
        if data['command'] == 'leave':
            print(message.user.username)
            diconnect_user(message, message.user.username)
            content = {'test': 'test'}
            Group(public_name).send({'text': json.dumps(content)})
            print('test_msg sent!')
            return

    if data['message'] == 'get_card':
        card = test_compare.shuffle_card(2)
        message.channel_session['card'] = card
        message.channel_session['hold_click_cnt'] = 0
        content = {
            'card': card,
            'status': 'start',
            'hold_click_cnt': message.channel_session['hold_click_cnt']
        }
        Group(public_name).send({'text': json.dumps(content)})

    elif data['message'] == 'hold':
        message.channel_session['hold_click_cnt'] += 1
        if (message.channel_session['hold_click_cnt'] < 3):
            content = {
                'card': message.channel_session['card'],
                'status': 'hold',
                'hold_click_cnt': message.channel_session['hold_click_cnt'],
                'result': ""
            }
        else:
            result = test_compare.decide_winner(
                message.channel_session['card'])
            content = {
                'card': message.channel_session['card'],
                'status': 'hold',
                'hold_click_cnt': message.channel_session['hold_click_cnt'],
                'result': result
            }
        Group(public_name).send({'text': json.dumps(content)})

    elif data['message'] == 'fold':
        result = "You lose!"
        message.channel_session['hold_click_cnt'] += 1
        message.channel_session['hold_click_cnt'] = 0
        content = {
            'card': message.channel_session['card'],
            'status': 'fold',
            'hold_click_cnt': message.channel_session['hold_click_cnt'],
            'result': result
        }
        Group(public_name).send({'text': json.dumps(content)})

    elif data['message'] == 'timeout':
        print('timeout')


# Connected to websocket.connect
@transaction.atomic
@channel_session_user_from_http
def ws_add(message):
    desk = Desk_info.objects.get(desk_name='desk0')

    # an global private group name array for each player
    private_group = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

    # an public group name for all player
    public_name = desk.desk_name

    # max compacity
    max_capacity = desk.capacity

    # list of players
    players = {}

    # test
    # desk.is_start = False
    # desk.save()

    # Add them to the public group
    Group(desk.desk_name).add(message.reply_channel)

    if desk.is_start:
        # Reject the incoming connection
        message.reply_channel.send({"accept": True})
        content = {'is_start': 'yes'}
        Group(public_name).send({'text': json.dumps(content)})
        Group(public_name).discard(message.reply_channel)
        return

    if desk.current_capacity == 0:
        # Reject the incoming connection
        message.reply_channel.send({"accept": True})
        content = {'is_full': 'yes'}
        desk_manipulation.disable_desk(desk)
        Group(public_name).send({'text': json.dumps(content)})
        Group(public_name).discard(message.reply_channel)
        return

    this_user = get_object_or_404(User, username=message.user.username)
    this_user_info = User_info.objects.get(user=this_user)

    this_position = int(desk.position_queue[0])
    desk.position_queue = desk.position_queue[1:]
    print(this_user_info)

    # Allocate a postion to the user
    player = User_Game_play(
        user=this_user_info, desk=desk, position=this_position)
    player.desk = desk
    player.save()

    player = User_Game_play.objects.get(user=this_user_info)
    print(player)

    if desk.current_capacity == max_capacity:
        desk.owner = this_user_info

    desk.current_capacity -= 1
    print(desk.current_capacity)

    # Accept the incoming connection
    message.reply_channel.send({"accept": True})
    message.channel_session['hold_click_cnt'] = 0

    # Add them to the public group
    Group(public_name).add(message.reply_channel)

    # Add the user to the private group
    position = str(player.position)
    Group(position).add(message.reply_channel)
    Group(position).send({'text': desk.desk_name})

    # Give owner signal
    if desk.owner == this_user_info:
        Group(position).send({'text': 'owner!'})

    # Boardcast to all player
    content = {'new_player': message.user.username,'position': player.position}
    Group(public_name).send({'text': json.dumps(content)})

    # If current player is 2 or more, owner can start the game
    if desk.current_capacity == max_capacity - 2:
        content = {'can_start': 'yes'}
        this_player = User_Game_play.objects.get(user=desk.owner)
        print(this_player.position)
        Group(str(this_player.position)).send({'text': json.dumps(content)})

    print('c:%d,m:%d,f:%d,o:%s,p:%s' %
          (desk.current_capacity, desk.capacity, desk.is_start,
           desk.owner.user.username, player.position))

    player.save()
    desk.save()
    print("after enter: ", desk)


# Connected to websocket.disconnect
@transaction.atomic
@channel_session_user_from_http
def ws_disconnect(message):
    print('disconnect!')
    # Disconnect
    # get desk
    # TODO: the desk_name can be dynamic when support multi-desk
    desk = Desk_info.objects.get(desk_name='desk0')
    # print(desk)
    #Group(public_name).discard(message.reply_channel)
    print('success')
    desk.current_capacity += 1

    # decide how to change is_start
    if desk.current_capacity >= desk.capacity - 1:
        desk.is_start = False

    # decide who is the next owner
    this_user_info = User_info.objects.get(user=message.user)
    this_player = User_Game_play.objects.get(user=this_user_info)
    if desk.owner == this_user_info:
        players = User_Game_play.objects.filter(desk=desk)
        # print(players)
        if len(players) == 1:
            # if this is the last user, desk.owner = None
            desk.owner = None
        else:
            # if still have people in the current desk, give the owner to him
            for player in players:
                if player != this_player:
                    desk.owner = player.user
                    break
    desk.save()
    # delete User_Game_play
    User_Game_play.objects.get(user=this_user_info).delete()
    Group(desk.desk_name).discard(message.reply_channel)
    return