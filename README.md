## Multiutility Bot 
Python bot in python-telegram-bot


## Deployment 

Make sure python3.12 is installed with FFMPEG + git + zip on server
```
sudo dnf update && sudo dnf install p7zip p7zip-plugins unrar -y
```
```
sudo apt update && sudo apt install p7zip-full unrar -y
```

Clone the repo 
```
git clone https://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@github.com/maniksaluja/helperbot
```

Install dependencies 
```
pip install -r requirements.txt
```

### Important to know
Telegram bot will use python-telegram-bot library for all bot functions, 
For Db we use mongoDb in config.py we will make sure we have dedicated util/db.py file to handle and manage eveyrhing.
utils/cronJob.py Global cron system for all function in this file.
As it has multiple feewtaures we use plugin folder to create dedicated file for each function no duplicates
Some featires


## Core features..
1. Unzipper: Unzip files sent by owner.
2. Membership: Channel+Group Membership to approve decline user and auto manage users managed by owner.
3. Reaction: Using pyrogram session string when reacted on any media save that media in saved message of user.
4. Old Forwarding: Forward media from an exesting channel to target channel from msgx to msgy.
5. Live Forwarding: As per desired settings forward all media from channelx to channely only new messages.
6. Batch Link: Create batchs for media sent from any channel to bot and create shareable links can be shared.
7. Broadcast : Owner can broadcast message to users.
8. Users Stats: /stats Show bot stats Total members, membership stats , Unzipper Stats 
9. SessionGEN: Generate pyrogram/telethon session Strings.

          

## Features Summry
### Unzipper. 
Owner sends any zip file , url in message with /unzip $msg or reply to a message with /zip 
Send message in reply to zip file with progress message i.e Checking zip file | Downloading zip file of $size | Extracting zip file | Extraction Completed Sending files (with progress) etc 
Add in Queue always - Then process the files. if its link before downloading check size if its a telegram file do check size and make sure on server we have enough size to extract the zip content.
Then download the zip file in a data/zips/$file_name-$time.zip and extract in maybe /data/unzipped/$folder_name
In case file is password protected on unzip ask user for password in message with button to cancel that will cancel the process, remove zip file etc. else if user provided the pass then delted the password asking msg and unzip. and send files to user now here in case we have any video files make sure to use ffmpeg to convert all videos to mp4 then send file as media (with preview and file name without extesnion and size)

In case a zip is in progress owner sends another request add that in queue and wait for 1st to complet once first is completed/failed zip file is deleted then process then next from queue.

### Membership
Groups Channels Membership system.
So on bot start we bot will check in which groups bot is admin with permession to kick users/invite user (Create invite links) on bot restart make sure to check exesting and if bot does not have access to exesting group mark as inactive. 
Now when bot is in a group we add in DB with Group Name, access link 

Now owner uses command i.e /membership it will show all groups where bot is admin with powers.
Show group name, Members (we get get memebers everytime on this command)
Access link i.e: t.me/$bot_username?start=membership$base64encodeddata 


Users side: When owner share access link with anyon check if user is already in group then send message.
You already have access in $group_name \nJoined $group_joining_date\nExpiring: $membership_expiring_date
Else if user is not in group: Then send a message: Your request to join $group_name is sent to admins\nWe will review your request and update you soon.

At same time send message to owner: #membership Reequest to join $group_name by $mention_user.
Show buttons 1d , 7d, 30d, 90d, Decline  (get days values from config.py i.e membership_days = [1,7,30,90])

Now in case owner declines the request Send message to user;
Sorry your request to join $group_name was rejected by admin.
If you need further assistantce contact support
BUTTON: support_username (button with link to open chat with support_username)

If approved send message to user.
Your request to join $group_name is approved\n
Joining data: $now \n
Expiring $membership_expiring_date \n\n
Click below button to join 
JOIN NOW (bot will create a link to join 1 user can join link validity = 24 hours)

For owner the Joining message we sent in start now will be updated (message that show decline days button)with message; You have approved $tag_user (mention the user) to join $group_name \nValid till $membership_expiring_date

Now as user in group: We run global crons using cronJob.py file it will run every 10 minutes.
And for each membership in DB we have joining and expiring date with groups ids.
Now for any user whose subscription is about to expire send them a message. 
Your membership in $group_name is expired. 
And you have no longer access, To renew your membership contact support (button with support_username) and remove that user from that specific group where membership is expired.


### Reaction Forwarder.

This is very important function in bot.
We use session string possibally pyrogram2.x i.e REACTION_STRING and save session file as reaction-*
Now logic is simple and easy when we start the bot we will init bot , db, cron and assitants (other assistants)
Now the session string will init and get all groups where this user has joined any group/channel and save them in cache (we dont need to save in DB)
Now whenever the user i.e REACTION_STRING reacts on any message in group/channel/private message of user|bot
We will forward that message to REACTION_FORWARDTO i.e saved|$tg_userid 
REACTION_FORWARDTO can be either saved so forward message to saved messsages of same user else if its a number means its a telegram user if its starts with -100 its a group or channel where we have to forward the message 

When forwarding the messag make sure to hide the sender info, 
Force forward somehow the message in groups/channels where forwarding is disabled 
Make sure to maintain the albums so if a message is album i.e multiple media send that as album.
Clean caption. The message and/or caption if has any link , telegrma username remove that and keep rest of the caption and send.
Make sure we always forward message as media.


### Old Forwarding.

Old forwarder aka oldfwd files will be named oldfwd_xxx.py 
So what will be the logic we use OLDFORWARDING_STRING pyrogram session we already have another for live_forwarder so make sure we start all gracefully 
Once initilated we will hanlde the old_forwarding we can port code from Live Forwarding.

So the logic when every owner sends any telegram link it can be private/public post link.
Now using the OLDFORWARDING_STRING assistant we will get the group info and post id. 
And consider this as start_fmsg send message to owner.

Hey, Seems its Old Forwarding task.\n
Group name: $group_name
Group id: $group_id
Message id: $startmsg_id
Now send me last message to prcess.
CANCEL BUTTON (to cancel the process)


Now wait for next telegram link -
When sent read and take this.
And send message make sure group_id is similar 

Ok So starting msg id $start_msgid and ending at $endmsg_id
Now i will forward $total_mediatoForwardinOldforwarder

Choose button below where i have to forward $total_mediatoForwardinOldforwarder media.

CANCEL BUTTON 
-- ALL GROUP --
(ALL group so here on top show SAVED MSG then scan and get users all groups/channels and show names of all woth prev-button)
So user can click on any group or SAVED MSG if saved msg then fowrad in saved msgs else if a group/channel is choosen then forward to that group.

Forwarding: Make sure we port exesting code from #mnetion and live_forwarding logic we have.
So if forwarding is disabled in group we have to download media/files with thumbnail, clean caption with removed username and links but keep terabox links.
Make sure caption is copied as is i.e with double qoute, bold as per telegram formatting.


Now oner click on any group - 
we will lock this in scheduler and start forwarding specfici messgae in between start-endmsgid
And show progress update with 5 seconds time.

Like: 
Old Forwarder Progress
From group: $from_group_id
Sending in $choosen_group_id
Total $total_mediatoForwardinOldforwarder messages to fwd.

-- [|||||||_____] %xx
Remaning xx of yy 



Once completed update the message with 
Forwarded xx message from $group_id to $group_id 
Time taken :$time_consumed 




### Live Forwarding.
So this is live forwarding feature.
So here we use pyrogram session string we use FORWARDING_STRING in config.py we have to init it first same other string session. 

So here owners can add forwarders i.e newForwarder using command /forward
So it will show current newforwarding rules, with status as active added: $added_time and show a button to ADD NEW FORWARDER 
When we click on the button it send message - With instruction and Ask user to enter group id with cancel button that will delete this message cancel the process and show the active forwarder.
with -100xxx from group where we have to foraward content from i.e origin group.
When owner enters the ID get group Info show name and of group - 
And then ask for Target Group ids with cancel button.

Now when owner enters target group id get name and show confirmation like
New Forwarder added
From group: $origin_group
To Group: $target_group 
Use /forward to see active NEW_Forwarders.

So here we show each active groups with details like Added Date, Status, Origin group, Target Group and a button to enable|disable and delete button for each forwarder 
When we click on DISABLE button forwarder will be disabled we now show ENABLE and DELETE button etc.
Make sure in scheduler we stop forwarding.

How it works.
When a forwarder is added and active
So whenever in origin_group any new post is added that will be forwarded in origingroup.
We have to forward everything media/gif/emoji/text/video etc
Now in case we have forwarding disabled then we have to download the content and send to origin_group 
We have to make sure we download thumbnails if its media and forwarding is disabled you can check reaction plugin for refrence how we get thumbnails.
Also we have to keep things in queue in case we get too many messages in origin_group and make sure to respect telegram limits.


### Batch Link
Batch Link is to create batch links on bot using using 2 commands /batch /makeit and /cancel .
So when we send /batch command to bot - bot will ask owner for media we forward/send telegram message to bot - bot will be in that group and bot will have access to media.
So bot will save all message ids, group id and create a batchid for this batch. 
and at end we send /makeit to save in DB 
Now in DB we have batchid, access_token, messages_id 

batchid will be unqiqe used to identify/edit batches later.
access_token a token we use that will be shared with users i.e https://t.me/$bot_token?start=batch$batchid, owner will get notification that user #mention has requestsed access to $batch_id 
Owner can click on buttons, DECLINE , ALLOW , ALLOW RESTRICTED 
DECLINE will decline the request and send message to user : your request for $batchid was decline
ALLOW: User will get message that Permession is granted, and user will recieve all message as forwarded from groups with specific message ids - 
ALLOW RESTRICTED: Same as allow but user its restricted mode, user can not forward/save message/media if restricted mode is enabled.

In case user request access for same batch again - then a new request will be sent again.
During making the batch if owner want to cancel can use /cancel to cancell the process.

/batches command will show all created batched i.e
Total $count batches 
$num: Batch: $batch_id
Source Group: $source_group_id
Total Media: $msgsids_count
Created on: $creating_date
Updated on: $updated_data


EDIT A BATCH - 
/editb $batch1 
When sent by owner - 
it will show selected batch info i.e
Update batch $batchid
You can send new messages to expland batch.

Now here user sends telegram message/forward messages bot will get message id with group if (groups can be multiple so same message ids are possible i.e groupa msgid1 , groupB msgid1)

/makeit will update the batch.


Make sure we save messages in util/responses.py file.
Make sure we dont breakanything - 
Create plugin file and required files if needed to import something we already have do import that.




### Broadcats
So here we have broadcast feature.
Owner can use /broadcast followed by message or reply to message with /broadcast 
Bot will get active users from DB in in DB we have can_broadcast then get users only from  can_broadcast else get all users always exclude users if can_broadcast = false 
Now send message to owner.

Broadcast Ready.
Total users: $total_users
Broadcating to: $can_broadcast_users | $total_users
ETA: $broadcast_eta 

Now here we will forward/send broadcast to users with safe sleep i.e every second we will send about 20 messages and sleep 1 second - 
Respect telegram ratelimit - it ratelmited then sleep 5 seconds 

Keep updating Broadcast progress message (update exesting msgs)
Broadcast Ongoing.
Total users: $can_broadcast_users | $total_users
Sent to $success_bcount
Failed: $failed_bcount
ETA: 12m

Once broadcast if finisded we will udpate message with full stats now
Here for all users who can not recoeve message i.e user has bloacked the bot that user will be added in can_broadcast = false 
Now when we get users we have to make sure we exclude users if user is can_broadcast = false 


### User Stats 
Users & Bot stats usable by owner only - /stats /users
So it will get all users from DB - possible other all possible info 
Active Batches - Active Forwarders - Active Membership 

Membership Status
Total Groups: $groups_using_membershop
Access Granted: $active_users_ingroups_using_membershipplugin_lifetime
Members Joined Today: $members_count_acceptedtoday 
Members Joined Monthly: $members_count_acceptedthisMonth

Batch Status
Active Batches : $batch_count
Acceped Batch Request:$acceptedbatchcount
Total Media in Batchs: $allmsgidsinallbatchs.

Unzipper Status
Total Unzipped: $unzipped_count
Failed unzipped; $failed_unzipped_count.
Total Size: $unzipped_total_size_lifetime.

Server Info.
CPU: $cpu_cores/$cpu_model ($percent_cpu_usage)
RAM: $used_ram/$total_ram
Disk: $disk_Count (Free:$free_disk)

### SessionGEN 
Generate Telegram Session strings for pyrogram and telethon 
So any user can send /session it will reply with message.
Welcome i can generate session strings for pyrogram and telethon\nChoose a button to continue.
PYROGRAM 2x | TELTHON \nCANCEL 
If cancelled cancell the process else if picked Pyrogram then init the pyrogram session string generation.
As user for phone number with countery code i.e
Now send me phone number for which you want pyrogram session string with country code \nExample: +917890000001

Now wher user enters the phone number make sure to chekc the phone number if formate is correct.
And init the request and if OPT sent Update deleted bots last message where we asked for number
Send new message: OTP Send on your telegram app send me the OTP 

Now wait for users message when user enters the OTP the process and see if 2-step if added an need 2-step password is so delete botlast message send new: 2-Step is enbled on your account\nHint:$get_hint \nSend me 2-step auth password.

Wait and read the message is session string is generated then send user the messge 
Your pyroram session string for $phone_number
CodeBlock (user can copy to click) also as spolier)) $session_string

Now save the data in DB in collection sessions_string with data linke
session_string, session_generted, session_otp (otp that was used) session_auth (2step if else null)session_phone, session_gendate (session generation dta)
