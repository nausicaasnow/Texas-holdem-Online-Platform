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


@transaction.atomic
def delete_desk(desk):
    desk.delete()


@transaction.atomic
@channel_session_user
def disconnect_user(message, username):
    print('disconnect!')
    # Disconnect
    print(username)
    # get desk
    public_name = message['path'].strip('/').split('/')[-1]
    print(message['path'].strip('/').split('/')[-1])
    desk = Desk_info.objects.get(desk_name=public_name)
    max_capacity = desk.capacity
    # Group(public_name).discard(message.reply_channel)
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

    if desk.current_capacity == desk.capacity:
        delete_desk(desk)
    return


@transaction.atomic
def start_logic(public_name):
    print('start signal received!')
    # let the user in lowest position be the dealer
    cur_desk = Desk_info.objects.get(desk_name=public_name)
    users_of_cur_desk = User_Game_play.objects.filter(
        desk=cur_desk).order_by('position')
    print(users_of_cur_desk)
    active_users_queue = ''
    for user in users_of_cur_desk:
        active_users_queue += str(user.position)
    cur_desk.player_queue = active_users_queue
    print('active_users_queue:', active_users_queue)  # test
    cur_desk.save()
    # find the index of the current dealer
    if cur_desk.next_dealer == -1:  # next_dealer is initialized as -1
        dealer_queue_pos = 0
    else:
        find_next = False
        for index, pos in enumerate(active_users_queue):
            if int(pos) == cur_desk.next_dealer:
                dealer_queue_pos = index
                find_next = True
            if not find_next and int(pos) > cur_desk.next_dealer:
                dealer_queue_pos = index
                find_next = True
        if not find_next:
            dealer_queue_pos = 0
    print('dealer_queue_pos:', dealer_queue_pos)
    dealer = User_Game_play.objects.get(
        desk=cur_desk, position=int(cur_desk.player_queue[dealer_queue_pos]))

    # let the next two player be blinds
    # next_pos_in_queue = get_next_pos(0, len(users_of_cur_desk))
    next_pos_in_queue = get_next_pos(dealer_queue_pos, cur_desk.player_queue)
    # update next_dealer
    cur_desk.next_dealer = int(cur_desk.player_queue[next_pos_in_queue])
    print('next_dealer:', cur_desk.next_dealer)
    cur_desk.save()
    # calculate small_blind and big_blind
    small_blind = User_Game_play.objects.get(
        desk=cur_desk, position=int(cur_desk.player_queue[next_pos_in_queue]))
    # next_pos_in_queue = get_next_pos(next_pos_in_queue, len(users_of_cur_desk))
    next_pos_in_queue = get_next_pos(next_pos_in_queue, cur_desk.player_queue)
    big_blind = User_Game_play.objects.get(
        desk=cur_desk, position=int(cur_desk.player_queue[next_pos_in_queue]))

    # the person move next is the next position of big_blind
    # cur_desk.player_queue_pointer = get_next_pos(next_pos_in_queue,
    #                                              len(users_of_cur_desk))
    cur_desk.player_queue_pointer = get_next_pos(next_pos_in_queue,
                                                 cur_desk.player_queue)

    # give every users 2 cards
    cards = test_compare.shuffle_card(len(users_of_cur_desk))

    # first 5 random cards give desk
    desk_cards = ''
    for card in cards[:5]:
        desk_cards += str(card) + ' '
    desk_cards = desk_cards[:-1]  # delete the last space character
    cur_desk.five_cards_of_desk = desk_cards

    # giver each users his cards and store it in the User_Game_play
    start_index = 5
    for user in users_of_cur_desk:
        cur_user_cards = ''
        for card in cards[start_index:start_index + 2]:
            cur_user_cards += str(card) + ' '
        cur_user_cards = cur_user_cards[:-1]
        start_index += 2
        user.user_cards = cur_user_cards

    for user in users_of_cur_desk:
        user.save()
        print("user after start: ", user)
        content = {'user_cards': user.user_cards}
        Group(str(user.position)).send({'text': json.dumps(content)})

    # tell the public channel, who is dealer, who is big blind, who is small blind
    content = {
        'dealer': [dealer.user.user.username, dealer.position],
        'big_blind': [big_blind.user.user.username, big_blind.position],
        'small_blind': [small_blind.user.user.username, small_blind.position],
        'start_game': 1
    }
    Group(cur_desk.desk_name).send({'text': json.dumps(content)})

    cur_desk.save()

    print("desk after start: ", cur_desk)
    return cur_desk.player_queue[cur_desk.player_queue_pointer]


# player_queue is a cyclic queue, the next pos of the last pos is 0
# def get_next_pos(cur_pos, len_queue):
#     if cur_pos <= len_queue - 2:
#         return cur_pos + 1
#     return 0


def get_next_pos(cur_pos, player_queue):
    len_queue = len(player_queue)
    for index, char in enumerate(player_queue):
        if cur_pos == int(char):
            pos = index
    if pos == len_queue - 1:
        return 0
    return pos + 1


def give_control(player_position, this_desk):
    print('give control to player position: ', player_position)
    this_user = User_Game_play.objects.get(
        desk=this_desk, position=player_position)
    content = {'move': {}}
    can_check, can_raise, raise_amount = True, False, 0
    if this_user.user.chips < this_desk.current_largest_chips_this_game - this_user.chips_pay_in_this_game:
        can_check = False
    content['move']['check'] = can_check
    if this_user.user.chips >= this_desk.current_largest_chips_this_game - this_user.chips_pay_in_this_game + this_desk.current_round_largest_chips:
        can_raise = True
        raise_amount = this_user.user.chips - this_desk.current_largest_chips_this_game
    content['move']['raise'] = [can_raise, [0, raise_amount]]
    Group(str(this_desk.desk_name)).send({'text': json.dumps(content)})


def find_next_player(desk, player):
    next_pos_queue = get_next_pos(player.position, desk.player_queue)
    desk.player_queue_pointer = next_pos_queue
    next_pos_desk = int(desk.player_queue[next_pos_queue])
    next_user = User_Game_play.objects.get(desk=desk, position=next_pos_desk)
    desk.save()
    return next_user


def judge_logic(next_player, desk):
    if len(desk.player_queue) == 1:
        print("judge logic only one player")
        assign_winner(desk, [[next_player.position]])
        return

    status = next_player.status
    # if next player hasn't moved in this turn, give control to him
    if status == 0:
        print("judge logic not moved")
        give_control(next_player.position, desk)
        return

    # if his status is all-in
    if status == -1:
        print("judge logic all-in")
        if next_player.chips_pay_in_this_game == desk.current_largest_chips_this_game:
            # go to winner_logic
            return winner_logic(desk)
        else:
            # update next player
            next_player = find_next_player(desk, next_player)
            return judge_logic(next_player, desk)

    # if his status is not fold
    if status == 1:
        print("judge logic moved")
        # if his bet is the highest bet in the table
        if next_player.chips_pay_in_this_game == desk.current_largest_chips_this_game:
            print("judge logic moved and equal to highest")
            # go to winner_logic
            return winner_logic(desk)
        else:
            # if his bet is not the highest bet in the table
            # give_control(next_player)
            print("judge logic b32")
            give_control(next_player.position, desk)


def assign_winner(desk, winner_list):
    print("winner list:", winner_list)
    # update the chips of current desk
    cur_pool = desk.pool
    while cur_pool > 0:
        for group in winner_list:
            # calculate how many chips needed in current group of winner to cover all in
            threshold = 0
            for winner_pos in group:
                cur_winner = User_Game_play.objects.get(
                    desk=desk, position=winner_pos)
                threshold += 2 * cur_winner.chips_pay_in_this_game
            if threshold <= cur_pool:
                # all in user can get all the chips he want,
                # the other chips are split equally by the remain winner
                not_all_in_cnt = 0
                for winner_pos in group:
                    cur_winner = User_Game_play.objects.get(
                        desk=desk, position=winner_pos)
                    if cur_winner.status == -1:
                        cur_winner.user.chips += cur_winner.chips_pay_in_this_game * 2
                        cur_pool -= cur_winner.chips_pay_in_this_game * 2
                    else:
                        not_all_in_cnt += 1

                if not_all_in_cnt:
                    for winner_pos in group:
                        cur_winner = User_Game_play.objects.get(
                            desk=desk, position=winner_pos)
                        if cur_winner.status != -1:
                            cur_winner.user.chips += cur_pool // not_all_in_cnt
                    # if there is at least one winner who is not all in, pool will become zero
                    cur_pool = 0
            else:
                # split the pool according to the ratio of the chips they put in this game
                for winner_pos in group:
                    cur_winner = User_Game_play.objects.get(
                        desk=desk, position=winner_pos)
                    cur_winner.user.chips += (
                        cur_winner.chips_pay_in_this_game /
                        (threshold // 2) * cur_pool)
                cur_pool = 0

    # reset the phase of the current desk
    desk.phase = 'pre_flop'
    desk.current_largest_chips_this_game = 0
    desk.pool = 0
    desk.current_round_largest_chips = 0

    # assign the winner, and show all the cards to all users
    cur_desk_users = User_Game_play.objects.filter(desk=desk)
    public_name = desk.desk_name
    all_user_cards = {}
    for user in cur_desk_users:
        all_user_cards[user.position] = user.user_cards
        # reset all users' chips_pay_in_this_game
        user.chips_pay_in_this_game = 0
        # reset status
        user.status = 0
        user.save()

    winner_pos_list = winner_list[0]
    winner_username = []
    for pos in winner_pos_list:
        cur_winner = User_Game_play.objects.get(desk=desk, position=pos)
        winner_username.append(cur_winner.user.user.username)
    content = {
        'winner_pos': winner_pos_list,
        'winner': winner_username,
        'cards': all_user_cards
    }
    Group(public_name).send({'text': json.dumps(content)})
    print("assign_winner success")

    print('start_game')
    first_player_position = start_logic(public_name)
    first_move_user = User_Game_play.objects.get(
        desk=desk, position=first_player_position)
    first_move_user.status = 1
    first_move_user.save()
    # '+1' added by lsn
    content = {
        'move': int(first_player_position) + 1,
        'current_round_largest_chips': desk.current_round_largest_chips
    }
    Group(public_name).send({'text': json.dumps(content)})


def winner_logic(cur_desk):
    # if there's only one player whose status is other than fold
    if len(cur_desk.player_queue) == 1:
        winner = User_Game_play.objects.get(
            desk=cur_desk, position=int(cur_desk.player_queue[0]))
        assign_winner(cur_desk, [[winner.position]])
        return

    # if this is the end of river phase
    if cur_desk.phase == 'river':
        # winner list is a sorted list, each element is a list contain user postions
        winner_list, results = river_compare(cur_desk)
        print(winner_list)
        # for test, just give the first person in the queue
        # winner = User_Game_play.objects.get(desk=cur_desk, position=winner_pos[0])
        assign_winner(cur_desk, winner_list)
        return

    # if there's only one player whose status is other than fold or all-in
    length = len(User_Game_play.objects.filter(desk=cur_desk, status=-1))
    if length >= len(cur_desk.player_queue) - 1:
        # TODO: go to river phase directly and assign a winner
        # all_in_compare()
        pass

    # continue the game to next phase
    return next_phase(cur_desk)


def river_compare(cur_desk):
    cur_cards = cur_desk.five_cards_of_desk
    public_card_list = list(map(int, cur_cards.split(' ')))
    print(public_card_list)
    all_user_card = []
    for i in cur_desk.player_queue:
        user = User_Game_play.objects.get(desk=cur_desk, position=i)
        tmp = (user.position,
               public_card_list + list(map(int, user.user_cards.split(' '))))
        all_user_card.append(tmp)
    print(all_user_card)
    winner, results = test_compare.decide_winner_all(all_user_card)
    return winner, results


def next_phase(cur_desk):
    public_name = cur_desk.desk_name
    print("next_phase")
    if cur_desk.phase == 'pre_flop':
        # show all users the first three cards of the desk
        cur_desk.phase = 'flop'
        cur_cards = cur_desk.five_cards_of_desk
        card_list = cur_cards.split(' ')
        for i in range(len(card_list)):
            card_list[i] = int(card_list[i])
        content = {'desk_cards': card_list[:3]}

    elif cur_desk.phase == 'flop':
        # show all users the first four cards of the desk
        cur_desk.phase = 'turn'
        cur_cards = cur_desk.five_cards_of_desk
        card_list = cur_cards.split(' ')
        for i in range(len(card_list)):
            card_list[i] = int(card_list[i])
        content = {'desk_cards': card_list[:4]}

    elif cur_desk.phase == 'turn':
        # show all users the first five cards of the desk
        cur_desk.phase = 'river'
        cur_cards = cur_desk.five_cards_of_desk
        card_list = cur_cards.split(' ')
        for i in range(len(card_list)):
            card_list[i] = int(card_list[i])
        content = {'desk_cards': card_list}

    Group(public_name).send({'text': json.dumps(content)})

    # let the player next to the dealer to move
    first_user = 0
    for i in cur_desk.player_queue:
        user = User_Game_play.objects.get(desk=cur_desk, position=i)
        if user.status != -1:
            user.status = 0
            user.save()
            if first_user == 0:
                first_user = 1
                continue
            if first_user == 1:
                first_user = 2
                next_user = user
    cur_desk.current_round_largest_chips = 0
    cur_desk.save()
    give_control(next_user.position, cur_desk)


@transaction.atomic
@channel_session_user
def ws_msg(message):
    public_name = message['path'].strip('/').split('/')[-1]
    print(message['path'].strip('/').split('/')[-1])

    try:
        data = json.loads(message['text'])
    except:
        return
    print(data)

    # the owner start the game
    if 'start_game' in data:
        print('start_game')
        first_player_position = start_logic(public_name)

        cur_desk = Desk_info.objects.get(desk_name=public_name)

        this_user = User_Game_play.objects.get(
            desk=cur_desk, position=first_player_position)
        this_user.status = 1

        cur_desk.is_start = True
        cur_desk.save()

        # '+1' added by lsn
        content = {'move': {}}
        can_check, can_raise, raise_amount = True, False, 0
        if this_user.user.chips < cur_desk.current_largest_chips_this_game - this_user.chips_pay_in_this_game:
            can_check = False
        content['move']['check'] = can_check
        if this_user.user.chips >= cur_desk.current_largest_chips_this_game - this_user.chips_pay_in_this_game + cur_desk.current_round_largest_chips:
            can_raise = True
            raise_amount = this_user.user.chips - cur_desk.current_largest_chips_this_game
        content['move']['raise'] = [can_raise, [0, raise_amount]]
        this_user.save()
        Group(public_name).send({'text': json.dumps(content)})
        return

    # The player click leave room
    if 'command' in data:
        if data['command'] == 'leave':
            print(message.user.username)
            #disconnect_user(message, message.user.username)
            return

    # get this_user, this_user_info, this_user_game_play, this_desk
    this_user = get_object_or_404(User, username=message.user.username)
    this_user_info = User_info.objects.get(user=this_user)
    this_user_game_play = User_Game_play.objects.get(user=this_user_info)
    this_desk = this_user_game_play.desk

    if data['message'] == 'call' or data['message'] == 'check' or data['message'] == 'hold':
        # current user put more chips
        print('current largest chips this game:',
              this_desk.current_largest_chips_this_game)
        print('current largest chips this round:',
              this_desk.current_round_largest_chips)
        print('this user chips pay in this game:',
              this_user_game_play.chips_pay_in_this_game)
        this_user_info.chips -= (this_desk.current_largest_chips_this_game -
                                 this_user_game_play.chips_pay_in_this_game)

        this_desk.pool += (this_desk.current_largest_chips_this_game -
                           this_user_game_play.chips_pay_in_this_game)
        this_user_game_play.chips_pay_in_this_game = this_desk.current_largest_chips_this_game
        this_user_game_play.status = 1
        next_pos_queue = get_next_pos(this_user_game_play.position,
                                      this_desk.player_queue)
        print('current largest chips this game:',
              this_desk.current_largest_chips_this_game)
        print('current largest chips this round:',
              this_desk.current_round_largest_chips)
        print('this user chips pay in this game:',
              this_user_game_play.chips_pay_in_this_game)

    elif data['message'] == 'fold' or data['message'] == 'timeout':
        # update the queue
        next_pos_queue = get_next_pos(this_user_game_play.position,
                                      this_desk.player_queue)
        this_desk.player_queue = this_desk.player_queue[:this_desk.player_queue_pointer] + \
                                 this_desk.player_queue[this_desk.player_queue_pointer + 1:]
        this_desk.player_queue_pointer -= 1
        this_user_game_play.status = 1
        if next_pos_queue > 0:
            next_pos_queue -= 1

    elif data['message'] == 'raise':
        print('current largest chips this game:',
              this_desk.current_largest_chips_this_game)
        print('current largest chips this round:',
              this_desk.current_round_largest_chips)
        print('this user chips pay in this game:',
              this_user_game_play.chips_pay_in_this_game)
        this_user_info.chips -= (this_desk.current_largest_chips_this_game -
                                 this_user_game_play.chips_pay_in_this_game)

        this_desk.pool += (this_desk.current_largest_chips_this_game -
                           this_user_game_play.chips_pay_in_this_game)
        this_user_game_play.chips_pay_in_this_game = this_desk.current_largest_chips_this_game

        chips_add = data['value']
        # current user put more chips
        this_user_info.chips -= chips_add
        this_user_game_play.chips_pay_in_this_game += chips_add
        this_desk.current_largest_chips_this_game = this_user_game_play.chips_pay_in_this_game
        this_desk.pool += chips_add
        if chips_add < this_desk.current_round_largest_chips:
            print(
                "Invaid!!!, chips_add < this_desk.current_round_largest_chips")
        this_desk.current_round_largest_chips = data['value']
        next_pos_queue = get_next_pos(this_user_game_play.position,
                                      this_desk.player_queue)
        this_user_game_play.status = 1
        print('current largest chips this game',
              this_desk.current_largest_chips_this_game)
        print('current largest chips this round',
              this_desk.current_round_largest_chips)
        print('this user chips pay in this game',
              this_user_game_play.chips_pay_in_this_game)

    elif data['message'] == 'all_in':
        this_desk.pool += this_user_info.chips
        this_user_game_play.status = -1
        raise_amount = this_user_info.chips - (this_desk.current_largest_chips_this_game - this_user_game_play.chips_pay_in_this_game)
        if raise_amount > this_desk.current_round_largest_chips:
            this_desk.current_round_largest_chips = raise_amount
        if this_user_info.chips + this_user_game_play.chips_pay_in_this_game > this_desk.current_largest_chips_this_game:
            this_desk.current_largest_chips_this_game = this_user_info.chips + this_user_game_play.chips_pay_in_this_game
        this_user_info.chips = 0

    # this_user_info.save()
    this_user_game_play.save()
    this_desk.save()
    this_user_info.save()

    this_desk.player_queue_pointer = next_pos_queue
    next_pos_desk = int(this_desk.player_queue[next_pos_queue])
    print('next_pos_desk: ', next_pos_desk)
    next_user = User_Game_play.objects.get(
        desk=this_desk, position=next_pos_desk)

    content = {
        'cur_user_pos': this_user_game_play.position + 1,
        'cur_user_chips': this_user_info.chips,
        'total_chips_current_game': this_desk.pool,
        'cur_user_chips_this_game': this_user_game_play.chips_pay_in_this_game
    }
    print(content)
    Group(public_name).send({'text': json.dumps(content)})

    # save the modified model, send the public group which user should move the next round
    this_user_info.save()
    this_user_game_play.save()
    this_desk.save()
    print("next_user before judge logic: ", next_user)
    judge_logic(next_user, this_desk)


# Connected to websocket.connect
@transaction.atomic
@channel_session_user_from_http
def ws_add(message):
    public_name = message['path'].strip('/').split('/')[-1]
    print(message['path'].strip('/').split('/')[-1])
    desk = Desk_info.objects.get(desk_name=public_name)

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
    # print(this_user_info)

    # Allocate a postion to the user
    player = User_Game_play(
        user=this_user_info, desk=desk, position=this_position)
    player.desk = desk
    player.save()

    player = User_Game_play.objects.get(user=this_user_info)
    print("created player")
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

    player.save()
    desk.save()

    # Boardcast to all player
    content = {
        'new_player': message.user.username,
        'position': player.position
    }
    Group(public_name).send({'text': json.dumps(content)})

    # If current player is 2 or more, owner can start the game
    if desk.current_capacity <= max_capacity - 2:
        content = {'can_start': 'yes'}
        this_player = User_Game_play.objects.get(user=desk.owner)
        print(this_player.position)
        Group(str(this_player.position)).send({'text': json.dumps(content)})

    print('c:%d,m:%d,f:%d,o:%s,p:%s' %
          (desk.current_capacity, desk.capacity, desk.is_start, desk.owner,
           player.position))

    print("after enter: ", desk)


# Connected to websocket.disconnect
@transaction.atomic
@channel_session_user
def ws_disconnect(message):
    print('disconnect!')
    # Disconnect
    print(message.user)
    # get desk
    public_name = message['path'].strip('/').split('/')[-1]
    print(message['path'].strip('/').split('/')[-1])
    desk = Desk_info.objects.get(desk_name=public_name)
    max_capacity = desk.capacity
    # Group(public_name).discard(message.reply_channel)
    if not desk.is_start:
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

        # Boardcast to all player
        content = {
            'leave_player': message.user.username,
            'position': this_player.position
        }
        Group(public_name).send({'text': json.dumps(content)})

        # delete User_Game_play
        User_Game_play.objects.get(user=this_user_info).delete()
        Group(desk.desk_name).discard(message.reply_channel)

        desk.save()

        if desk.current_capacity == desk.capacity:
            delete_desk(desk)
        return
    else:
        # TODO: if the user leave room during the game
        pass

