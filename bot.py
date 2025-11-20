import asyncio
import os
import random
from telethon import TelegramClient
from telethon.tl.types import Channel, InputChannel, ForumTopic, InputPeerChannel
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest

SESSION_NAME = 'topic_forwarder_session'
LAST_ID_FILE = 'last_forwarded_id.txt'
TOPIC_MAP = {1: 1}

API_ID = None
API_HASH = None
SOURCE_GROUP = None
DESTINATION_GROUP = None
SKIP_TOPIC_IDS = []

def load_environment_variables():
    global API_ID, API_HASH, SOURCE_GROUP, DESTINATION_GROUP, SKIP_TOPIC_IDS

    env_vars = {}
    if not os.path.exists('.env'):
        return False

    print("Loading configuration from local .env file...")
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().replace('"', '').replace("'", '')

        raw_api_id = env_vars.get('TELEGRAM_API_ID')
        API_ID = int(raw_api_id) if raw_api_id else None
        API_HASH = env_vars.get('TELEGRAM_API_HASH')

        raw_source_group = env_vars.get('SOURCE_GROUP_ID')
        raw_dest_group = env_vars.get('DESTINATION_GROUP_ID')

        if raw_source_group:
            SOURCE_GROUP = int(raw_source_group)
        if raw_dest_group:
            DESTINATION_GROUP = int(raw_dest_group)

        skip_topics_str = env_vars.get('SKIP_TOPIC_ID', '')
        if skip_topics_str:
            SKIP_TOPIC_IDS = [int(i.strip()) for i in skip_topics_str.split(',') if i.strip().lstrip('-').isdigit()]

    except ValueError:
        print("Error: Group IDs or Topic IDs in .env must be valid integers.")
        return False
    except Exception as e:
        print(f"FATAL ERROR: Failed to read or parse the .env file: {e}")
        return False

    return all([API_ID, API_HASH, SOURCE_GROUP, DESTINATION_GROUP])

def load_last_id():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            try:
                content = f.read().strip().split(':')
                if len(content) == 2:
                    return int(content[0]), int(content[1])
                return 0, 1
            except ValueError:
                return 0, 1
    return 0, 1

def save_last_id(message_id, topic_id):
    with open(LAST_ID_FILE, 'w') as f:
        f.write(f"{message_id}:{topic_id}")

def get_destination_topic_id(source_topic_id):
    return TOPIC_MAP.get(source_topic_id, 1)

async def fetch_all_topics(client, entity):
    if not isinstance(entity, Channel):
        entity = await client.get_entity(entity)

    topics = {}
    seen_topic_ids = set()

    try:
        print(f"   Scanning messages to discover topics...")
        message_count = 0

        async for message in client.iter_messages(entity, limit=1000):
            message_count += 1

            if hasattr(message, 'reply_to') and message.reply_to:
                topic_id = None

                if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                    topic_id = message.reply_to.reply_to_top_id
                elif hasattr(message.reply_to, 'reply_to_msg_id'):
                    topic_id = message.reply_to.reply_to_msg_id

                if topic_id and topic_id not in seen_topic_ids:
                    seen_topic_ids.add(topic_id)

                    try:
                        topic_msg = await client.get_messages(entity, ids=topic_id)
                        icon_emoji_id = None

                        if topic_msg and not topic_msg.action:
                            title = topic_msg.message[:100] if topic_msg.message else f'Topic {topic_id}'
                        else:
                            if hasattr(topic_msg, 'action') and hasattr(topic_msg.action, 'title'):
                                title = topic_msg.action.title
                                if hasattr(topic_msg.action, 'icon_emoji_id'):
                                    icon_emoji_id = topic_msg.action.icon_emoji_id
                            else:
                                title = f'Topic {topic_id}'

                        topics[topic_id] = {
                            'id': topic_id,
                            'title': title,
                            'icon_emoji_id': icon_emoji_id
                        }
                        icon_info = f" (Icon: {icon_emoji_id})" if icon_emoji_id else ""
                        print(f"   Found topic {topic_id}: {title}{icon_info}")
                    except Exception as e:
                        print(f"   Could not fetch details for topic {topic_id}: {e}")
                        topics[topic_id] = {
                            'id': topic_id,
                            'title': f'Topic {topic_id}',
                            'icon_emoji_id': None
                        }

        print(f"   Scanned {message_count} messages, found {len(topics)} topics")

    except Exception as e:
        print(f"Error scanning messages for topics: {e}")

    if 1 not in topics:
        topics[1] = {'id': 1, 'title': 'General', 'icon_emoji_id': None}

    return sorted(topics.values(), key=lambda t: t['id'])


async def ensure_destination_topics(client, source_entity, dest_entity):
    print("--- 1. Ensuring Destination Topics Exist and Building Map (ALL Topics) ---")

    all_source_topics = await fetch_all_topics(client, source_entity)
    mappable_source_topics = [t for t in all_source_topics if t['id'] != 1]
    source_topics_by_title = {t['title']: t['id'] for t in mappable_source_topics}

    if SKIP_TOPIC_IDS:
        print(f"   Note: Topics in {SKIP_TOPIC_IDS} will be created, but their content will be skipped.")

    dest_topics = await fetch_all_topics(client, dest_entity)
    dest_topics_by_title = {t['title']: t['id'] for t in dest_topics if t['id'] != 1}

    for title, dest_id in dest_topics_by_title.items():
        if title in source_topics_by_title:
            source_id = source_topics_by_title[title]
            TOPIC_MAP[source_id] = dest_id
            print(f"   Mapped existing topic: Source {source_id} ('{title}') -> Dest {dest_id}")

    for topic in mappable_source_topics:
        source_id = topic['id']
        source_title = topic['title']

        if source_id not in TOPIC_MAP:
            icon_id = topic.get('icon_emoji_id', None)

            print(f"   Creating new topic in destination: '{source_title}' (Icon: {icon_id})...")

            try:
                input_channel = InputPeerChannel(
                    channel_id=dest_entity.id,
                    access_hash=dest_entity.access_hash
                )

                result = await client(CreateForumTopicRequest(
                    input_channel,
                    title=source_title,
                    icon_emoji_id=icon_id,
                    random_id=random.randint(-(2**63), 2**63 - 1)
                ))

                new_dest_id = None
                if hasattr(result, 'updates'):
                    for update in result.updates:
                        if hasattr(update, 'message') and hasattr(update.message, 'id'):
                            new_dest_id = update.message.id
                            break

                if new_dest_id:
                    TOPIC_MAP[source_id] = new_dest_id
                    print(f"   Created and Mapped: Source {source_id} ('{source_title}') -> Dest {new_dest_id}")
                else:
                    print(f"   ERROR: Could not extract topic ID from creation result! Skipping.")
            except Exception as e:
                 print(f"   FATAL TOPIC CREATION ERROR: Failed to create topic '{source_title}': {e}")

    print(f"--- Topic Map Completed: {TOPIC_MAP} ---")
    return all_source_topics


async def topic_migration_forwarder():
    last_forwarded_id, last_forwarded_topic = load_last_id()

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    try:
        source_entity = await client.get_entity(SOURCE_GROUP)
        dest_entity = await client.get_entity(DESTINATION_GROUP)

    except Exception as e:
        print(f"ERROR: Could not get entities using IDs '{SOURCE_GROUP}' or '{DESTINATION_GROUP}'. Ensure the IDs are correct and you are a member of both groups: {e}")
        await client.disconnect()
        return

    print(f"Connected. Last tracked ID: {last_forwarded_id} in Source Topic {last_forwarded_topic}")

    source_topics = await ensure_destination_topics(client, source_entity, dest_entity)

    start_index = next((i for i, t in enumerate(source_topics) if t['id'] == last_forwarded_topic), 0)
    topics_to_process = source_topics[start_index:]

    for topic in topics_to_process:
        source_topic_id = topic['id']

        if source_topic_id not in TOPIC_MAP:
            print(f"   WARNING: Source Topic {source_topic_id} ('{topic['title']}') could not be mapped. Skipping.")
            continue

        dest_topic_id = get_destination_topic_id(source_topic_id)

        print(f"\n--- Processing Source Topic {source_topic_id} ('{topic['title']}') -> Dest Topic {dest_topic_id} ---")

        if source_topic_id in SKIP_TOPIC_IDS:
            print(f"      Topic ID {source_topic_id} is in SKIP_TOPIC_IDS. Content migration skipped.")

            try:
                newest_message = await client.get_messages(
                    entity=source_entity,
                    reply_to=source_topic_id,
                    limit=1
                )
                if newest_message:
                    max_message_id = newest_message[0].id

                    if source_topic_id > last_forwarded_topic or \
                       (source_topic_id == last_forwarded_topic and max_message_id > last_forwarded_id):

                        last_forwarded_id = max_message_id
                        last_forwarded_topic = source_topic_id
                        save_last_id(last_forwarded_id, last_forwarded_topic)
                        print(f"      Marked content up to ID {max_message_id} as processed (Skipped Topic).")

            except Exception as e:
                print(f"      Warning: Could not fetch max ID to mark skipped topic {source_topic_id} as complete: {e}")

            continue

        topic_min_id = last_forwarded_id if source_topic_id == last_forwarded_topic else 0

        messages = await client.get_messages(
            entity=source_entity,
            min_id=topic_min_id,
            reply_to=source_topic_id,
            limit=5000
        )

        messages.reverse()

        if not messages:
            print(f"      No new messages found since ID {topic_min_id}. Moving to the next topic.")
            continue

        print(f"      Fetched {len(messages)} messages to process (starting from ID {topic_min_id + 1}).")

        for message in messages:
            if message.id <= last_forwarded_id and source_topic_id == last_forwarded_topic:
                 continue

            if message.id == source_topic_id and hasattr(message, 'action'):
                continue

            if not message.text and not message.media:
                continue

            print(f"      Forwarding Message ID {message.id} (Topic {source_topic_id})...")

            try:
                await client.send_message(
                    entity=dest_entity,
                    message=message,
                    reply_to=dest_topic_id
                )

                last_forwarded_id = message.id
                last_forwarded_topic = source_topic_id
                save_last_id(last_forwarded_id, last_forwarded_topic)

                await asyncio.sleep(0.25)

            except Exception as e:
                print(f"         ! ERROR forwarding Message ID {message.id}: {e}. Saving progress and continuing...")
                save_last_id(last_forwarded_id, source_topic_id)
                break

    print("\n--- Forwarding Complete ---")
    print(f"Final Last Forwarded ID saved: {last_forwarded_id} in Topic {last_forwarded_topic}")
    await client.log_out()


if __name__ == '__main__':
    if not load_environment_variables():
        print("\nFATAL ERROR: Mandatory configuration variables missing or invalid in the .env file.")
    else:
        print(f"Configuration Loaded. Source: {SOURCE_GROUP}, Destination: {DESTINATION_GROUP}, Skip Topics: {SKIP_TOPIC_IDS}")
        try:
            asyncio.run(topic_migration_forwarder())
        except KeyboardInterrupt:
            print("\nScript interrupted by user. Closing client.")
        except Exception as e:
            print(f"\nAn unhandled error occurred: {e}")
