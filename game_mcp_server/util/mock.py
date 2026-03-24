# -------------------------------------------------------------
# 本文件为 Unity MCP 服务端命令测试代码
# 运行指令（在 src 目录下）：
# uv run --directory .\UnityMcpBridge\UnityMcpServer~\src\ -m util.mock.py
# -------------------------------------------------------------
import asyncio
import json
import base64
from connection.connection_provider import get_current_connection


async def close():
    res = await get_current_connection().send_command(
        "close",
        {}
    )
    print(res)


async def export():
    res = await get_current_connection().send_command(
        "export",
        {
            "x-canvas-id": "test_canvas_id",
            "x-seele-canvas-trace-id": "test_trace_id_turn_1",
        }
    )
    print(res)


async def manage_gameobject():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "name": "Tank1",
            "prefabPath": "Assets/object/tank_search_01.glb",
            "action": "create",
            "position": [
                -8,
                0,
                3
            ],
            "rotation": [
                0,
                90,
                0
            ]
        }
    )
    print(res)


async def read_console():
    res = await get_current_connection().send_command(
        "read_console",
        {
            "x-canvas-id": "test_canvas_id",
            "x-seele-canvas-trace-id": "83dfaec4-8cb8-4a80-a5e7-95398b41036e|26826903-cf3a-4fc8-9353-14edd272368d|loop_flow-9cd3e14668eac844eabf9b69|manage_gameobject",
            "action": "get",
            "types": [
                "all"
            ],
            "count": 50,
            "format": "json",
            "include_stacktrace": True
        }
    )
    formatted_json = json.dumps(
        res, indent=4, ensure_ascii=False, sort_keys=False)
    print(formatted_json)


async def clear_console():
    res = await get_current_connection().send_command(
        "read_console",
        {
            "action": "clear",
            "types": [
                "error"
            ],
            "count": 50,
        }
    )
    print(res)


async def create_script():
    contents = "using UnityEngine;\n\npublic class SimpleCarController : MonoBehaviour\n{\n    [SerializeField] private float moveSpeed = 8f;\n    [SerializeField] private float turnSpeed = 120f;\n    [SerializeField] private bool useLocalRotation = true;\n\n    private void Update()\n    {\n        float moveInput = Input.GetAxis(\"Vertical\");\n        float turnInput = Input.GetAxis(\"Horizontal\");\n\n        if (useLocalRotation)\n        {\n            transform.Rotate(0f, turnInput * turnSpeed * Time.deltaTime, 0f);\n            transform.Translate(0f, 0f, moveInput * moveSpeed * Time.deltaTime, Space.Self);\n        }\n        else\n        {\n            Vector3 forward = new Vector3(0f, 0f, 1f);\n            transform.Translate(forward * moveInput * moveSpeed * Time.deltaTime, Space.World);\n            transform.Rotate(0f, turnInput * turnSpeed * Time.deltaTime, 0f);\n        }\n    }\n}\n"
    res = await get_current_connection().send_command(
        "manage_script",
        {
            "action": "create",
            "name": "SimpleCarController",
            "path": "Assets/Scripts",
            "encodedContents": base64.b64encode(contents.encode("utf-8")).decode("utf-8"),
            "namespace": None,
            "scriptType": None,
        }
    )
    print(res)


async def modify_particle_system():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "modify",
            "target": "HitEffect",
            "searchMethod": "by_name",
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "setActive": False,
            "componentProperties": {
                "ParticleSystem": {
                    "startColor": [1, 0.5, 0, 1],
                    "startSize": 0.3,
                    "startLifetime": 0.5,
                    "startSpeed": 3,
                    # "rateOverTime": 50,
                    "loop": False,
                    "Shape": {
                        "Shape": "Sphere"
                    },
                    "Renderer": {
                        "Material": "ParticleMaterial"
                    }
                },
            },
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": True,
            "x-canvas-id": "8a0d38ae-3de8-4c04-8895-05f4f381d3dc",
            "x-seele-canvas-trace-id": "8a0d38ae-3de8-4c04-8895-05f4f381d3dc|64453129-583e-4b18-9983-92b094d8b0f5|loop_flow-ae90edc64d1f2e8f7c18692b|manage_gameobject_a5fdbe7c-a7bc-4931-9a35-77f345bb2882",
            "trace_id": "86449a5c"
            }
    )
    formatted_json = json.dumps(
        res, indent=4, ensure_ascii=False, sort_keys=False)
    print(formatted_json)

async def get_hierarchy():
    res = await get_current_connection().send_command(
        "manage_scene",
        {
            "action": "get_hierarchy",
        }
    )
    print(res)


async def load_scene():
    res = await get_current_connection().send_command(
        "manage_scene",
        {
            "action": "load",
            "name": "SampleScene",
            "path": "Assets/Scenes",
        }
    )
    print(res)

async def import_avatar():
    res = await get_current_connection().send_command(
        "import_external_asset",
        {
            "url": "https://static.seeles.ai/data/asset/export/68426a74-6bb5-41e6-9f98-46cbeb3654fa/104203/model.fbx",
            "asset_id": "pirate_character_1_1_1",
            "category": "avatar",
            "auto_import": True,
            "all_assets": "{\"front_view_url\": \"https://static.seeles.ai/data/asset/export/bfbc7696-6885-4603-a463-1dddf63ade56/104203/cover_reader_deal_local/3060055_104203_1737257505844/front.png\", \"model_url\": \"https://static.seeles.ai/data/asset/export/68426a74-6bb5-41e6-9f98-46cbeb3654fa/104203/model.fbx\", \"web_url\": \"https://static.seeles.ai/data/asset/export/81a2bbe4-212a-4127-9cd6-56a9892b788b/104203/assetBundle/cd940ea17dc7f1ccdab5d302448e059d_web.zip\", \"ios_url\": \"https://static.seeles.ai/data/asset/export/c00cc05d-76f9-461c-921f-fbcbb6446197/104203/assetBundle/2551697e8654aa0ea4d8dc8a4348ebc1_ios.zip\", \"android_url\": \"https://static.seeles.ai/data/asset/export/596a202b-de32-4787-bb00-7f7750b4108c/104203/assetBundle/8cbfd409788aeff765522f7106b9a470_android.zip\", \"front_view_url_public\": \"https://static.seeles.ai/data/asset/export/bfbc7696-6885-4603-a463-1dddf63ade56/104203/cover_reader_deal_local/3060055_104203_1737257505844/front.png\", \"model_url_public\": \"https://static.seeles.ai/data/asset/export/68426a74-6bb5-41e6-9f98-46cbeb3654fa/104203/model.fbx\", \"web_url_public\": \"https://static.seeles.ai/data/asset/export/81a2bbe4-212a-4127-9cd6-56a9892b788b/104203/assetBundle/cd940ea17dc7f1ccdab5d302448e059d_web.zip\", \"ios_url_public\": \"https://static.seeles.ai/data/asset/export/c00cc05d-76f9-461c-921f-fbcbb6446197/104203/assetBundle/2551697e8654aa0ea4d8dc8a4348ebc1_ios.zip\", \"android_url_public\": \"https://static.seeles.ai/data/asset/export/596a202b-de32-4787-bb00-7f7750b4108c/104203/assetBundle/8cbfd409788aeff765522f7106b9a470_android.zip\"}",
            "name": "pirate_character_1_1_1",
            "x-canvas-id": "6eace23b-b7e2-4639-a251-079df366f219",
            "x-seele-canvas-trace-id": "6eace23b-b7e2-4639-a251-079df366f219|4db3e2bf-e865-44b9-b267-613f4b0b1e54|loop_flow-b2ec3ca2aa410ad974e3336f|import_external_asset_b8f8bf95-71b6-431b-aa07-5dc169f1d207",
            "trace_id": "6cf43613"
        }
    )
    formatted_json = json.dumps(
        res, indent=4, ensure_ascii=False, sort_keys=False)
    print(formatted_json)

async def import_model():
    res = await get_current_connection().send_command(
        "import_external_asset",
        {
        "url": "https://static.seeles.ai/media/game_asset/assets_a983a4fb_16e1_40d2_a6ff_4d76181a134f_1764827989373629038.glb",
        "asset_id": "beach_treasure_hunting_environment",
        "category": "object",
        "auto_import": True,
        "all_assets": "{\"model_url\": \"s3://seelemedia-private/PROD/blender_mcp/979c27a11331de595b132ae27eb67b4a_17648279397336441928081867908140.glb\", \"glb_url\": \"s3://seelemedia-private/PROD/blender_mcp/979c27a11331de595b132ae27eb67b4a_17648279397336441928081867908140.glb\", \"model_url_public\": \"https://static.seeles.ai/media/game_asset/assets_a983a4fb_16e1_40d2_a6ff_4d76181a134f_1764827989373629038.glb\", \"glb_url_public\": \"https://static.seeles.ai/media/game_asset/assets_13a82b24_e45f_4411_ab63_446e9b8dad48_1764827992337828527.glb\"}",
        "name": "beach_treasure_hunting_environment",
        "x-canvas-id": "6eace23b-b7e2-4639-a251-079df366f219",
        "x-seele-canvas-trace-id": "6eace23b-b7e2-4639-a251-079df366f219|4db3e2bf-e865-44b9-b267-613f4b0b1e54|loop_flow-b2ec3ca2aa410ad974e3336f|import_external_asset_aec095bb-7939-4977-b04e-ffdc588d9cae",
        "trace_id": "7b1bed05"
        }
    )
    formatted_json = json.dumps(
        res, indent=4, ensure_ascii=False, sort_keys=False)
    print(formatted_json)

async def search():
    # res = await get_unity_connection().send_command(
    #     "manage_asset",
    #     {
    #         "action": "search",
    #         "path": "Assets",
    #         "search_pattern": "HierarchyChangeExporter.cs",
    #         "page_size": 500,
    #         "page_number": 1
    #     }
    # )
    # print(res)
    res = await get_current_connection().send_command(
        "manage_asset",
        {
            "action": "search",
            "path": "Assets",
            # "properties": {
            #     "action": {
            #         "title": "Action",
            #         "type": "string"
            #     },
            #     "path": {
            #         "title": "Path",
            #         "type": "string"
            #     },
            #     "task_name": {
            #         "title": "Task Name",
            #         "type": "string"
            #     },
            #     "asset_type": {
            #         "title": "Asset Type",
            #         "type": "string"
            #     },
            #     "properties": {
            #         "type": "object",
            #         "additionalProperties": True,
            #         "title": "Properties"
            #     },
            #     "destination": {
            #         "title": "Destination",
            #         "type": "string"
            #     },
            #     "generate_preview": {
            #         "default": False,
            #         "title": "Generate Preview",
            #         "type": "boolean"
            #     },
            #     "search_pattern": {
            #         "title": "Search Pattern",
            #         "type": "string"
            #     },
            #     "filter_type": {
            #         "title": "Filter Type",
            #         "type": "string"
            #     },
            #     "filter_date_after": {
            #         "title": "Filter Date After",
            #         "type": "string"
            #     },
            #     "page_size": {
            #         "title": "Page Size",
            #         "type": "integer"
            #     },
            #     "page_number": {
            #         "title": "Page Number",
            #         "type": "integer"
            #     }
            # },
            "generatePreview": False,
            "searchPattern": "HierarchyChangeExporter.cs",
        }
    )
    print(res)


async def get_screenshot():
    res = await get_current_connection().send_command(
        "get_screenshot",
        {
            "target": "",
            "frame_mode": "scene",
            "canvas_id": "test_canvas_id",
        }
    )
    print(res)


async def switch_play():
    res = await get_current_connection().send_command(
        "manage_editor",
        {
            "action": "play"
        }
    )
    print(res)


async def execute_menu_item():
    res = await get_current_connection().send_command(
        "execute_menu_item",
        {
            "action": "execute",
            "menuPath": "Assets/Reimport All",
            "parameters": {},
        }
    )
    print(res)


async def import_image():
    await get_current_connection().send_command(
        "import_external_asset",
        {
            "url": "s3://seelemedia-private/TEST/gemini_image_gen/4961ed3b6b753d113b9db11bf7e92879_17588754839238235080225756423568.png",
            "asset_id": "test_image",
            "category": "image",
            "auto_import": True,
            "all_assets": {},
            "name": "test_image"
        }
    )


async def set_script():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "add_component",
            "target": "GameManager",
            "searchMethod": "by_name",
            "componentsToAdd": [
                "AnimalCrossingGameManager"
            ],
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "188c0c24-4fdb-4848-bb20-5423fcfb06f2",
            "x-seele-canvas-trace-id": "188c0c24-4fdb-4848-bb20-5423fcfb06f2|a9006edb-58c3-48ee-9e21-55cacb602f89|loop_flow-3cee09a8d09a72173b5d5c70|manage_gameobject_55e5e6a6-ca30-4b59-835c-1e22a800aa3a"
        }
    )
    print(res)


async def create_player_script():
    res = await get_current_connection().send_command(
        "manage_script",
        {
            "action": "create",
            "name": "AnimalCrossingGameManager",
            "path": "Assets/Scripts",
            "encodedContents": "dXNpbmcgVW5pdHlFbmdpbmU7CgpwdWJsaWMgY2xhc3MgQW5pbWFsQ3Jvc3NpbmdHYW1lTWFuYWdlciA6IE1vbm9CZWhhdmlvdXIKewogICAgW0hlYWRlcigiVHJlZSBQbGFudGluZyIpXQogICAgcHVibGljIEdhbWVPYmplY3RbXSB0cmVlUHJlZmFiczsKICAgIHB1YmxpYyBMYXllck1hc2sgZ3JvdW5kTGF5ZXIgPSAxOwogICAgCiAgICBbSGVhZGVyKCJCdWlsZGluZyIpXQogICAgcHVibGljIEdhbWVPYmplY3RbXSBidWlsZGluZ1ByZWZhYnM7CiAgICAKICAgIFtIZWFkZXIoIkdhbWUgTW9kZSIpXQogICAgcHVibGljIGVudW0gR2FtZU1vZGUgeyBOb25lLCBQbGFudFRyZWUsIEJ1aWxkIH0KICAgIHB1YmxpYyBHYW1lTW9kZSBjdXJyZW50TW9kZSA9IEdhbWVNb2RlLk5vbmU7CiAgICAKICAgIHByaXZhdGUgQ2FtZXJhIHBsYXllckNhbWVyYTsKICAgIAogICAgdm9pZCBTdGFydCgpCiAgICB7CiAgICAgICAgcGxheWVyQ2FtZXJhID0gQ2FtZXJhLm1haW47CiAgICAgICAgCiAgICAgICAgLy8g5Yqg6L296aKE5Yi25L2TCiAgICAgICAgTG9hZFByZWZhYnMoKTsKICAgIH0KICAgIAogICAgdm9pZCBMb2FkUHJlZmFicygpCiAgICB7CiAgICAgICAgLy8g5Yqo5oCB5Yqg6L295a+85YWl55qE6LWE5Lqn5L2c5Li66aKE5Yi25L2TCiAgICAgICAgR2FtZU9iamVjdCB0cmVlQXNzZXQgPSBSZXNvdXJjZXMuTG9hZDxHYW1lT2JqZWN0Pigib2JqZWN0L3RyZWVfY29sbGVjdGlvbl8xIik7CiAgICAgICAgR2FtZU9iamVjdCBob3VzZUFzc2V0ID0gUmVzb3VyY2VzLkxvYWQ8R2FtZU9iamVjdD4oIm9iamVjdC9ob3VzZV9jb2xsZWN0aW9uXzEiKTsKICAgICAgICAKICAgICAgICBpZiAodHJlZUFzc2V0ID09IG51bGwpCiAgICAgICAgewogICAgICAgICAgICB0cmVlQXNzZXQgPSBHYW1lT2JqZWN0LkZpbmQoInRyZWVfY29sbGVjdGlvbl8xIik7CiAgICAgICAgfQogICAgICAgIAogICAgICAgIGlmIChob3VzZUFzc2V0ID09IG51bGwpCiAgICAgICAgewogICAgICAgICAgICBob3VzZUFzc2V0ID0gR2FtZU9iamVjdC5GaW5kKCJob3VzZV9jb2xsZWN0aW9uXzEiKTsKICAgICAgICB9CiAgICAgICAgCiAgICAgICAgaWYgKHRyZWVBc3NldCAhPSBudWxsKQogICAgICAgIHsKICAgICAgICAgICAgdHJlZVByZWZhYnMgPSBuZXcgR2FtZU9iamVjdFtdIHsgdHJlZUFzc2V0IH07CiAgICAgICAgfQogICAgICAgIAogICAgICAgIGlmIChob3VzZUFzc2V0ICE9IG51bGwpCiAgICAgICAgewogICAgICAgICAgICBidWlsZGluZ1ByZWZhYnMgPSBuZXcgR2FtZU9iamVjdFtdIHsgaG91c2VBc3NldCB9OwogICAgICAgIH0KICAgIH0KICAgIAogICAgdm9pZCBVcGRhdGUoKQogICAgewogICAgICAgIEhhbmRsZUlucHV0KCk7CiAgICB9CiAgICAKICAgIHZvaWQgSGFuZGxlSW5wdXQoKQogICAgewogICAgICAgIC8vIOmUruebmOi+k+WFpeWIh+aNouaooeW8jwogICAgICAgIGlmIChJbnB1dC5HZXRLZXlEb3duKEtleUNvZGUuVCkpCiAgICAgICAgewogICAgICAgICAgICBTZXRHYW1lTW9kZShHYW1lTW9kZS5QbGFudFRyZWUpOwogICAgICAgIH0KICAgICAgICBlbHNlIGlmIChJbnB1dC5HZXRLZXlEb3duKEtleUNvZGUuQikpCiAgICAgICAgewogICAgICAgICAgICBTZXRHYW1lTW9kZShHYW1lTW9kZS5CdWlsZCk7CiAgICAgICAgfQogICAgICAgIGVsc2UgaWYgKElucHV0LkdldEtleURvd24oS2V5Q29kZS5Fc2NhcGUpKQogICAgICAgIHsKICAgICAgICAgICAgU2V0R2FtZU1vZGUoR2FtZU1vZGUuTm9uZSk7CiAgICAgICAgfQogICAgICAgIAogICAgICAgIC8vIOm8oOagh+eCueWHu+aUvue9rueJqeWTgQogICAgICAgIGlmIChJbnB1dC5HZXRNb3VzZUJ1dHRvbkRvd24oMCkgJiYgY3VycmVudE1vZGUgIT0gR2FtZU1vZGUuTm9uZSkKICAgICAgICB7CiAgICAgICAgICAgIEhhbmRsZVBsYWNlbWVudCgpOwogICAgICAgIH0KICAgIH0KICAgIAogICAgcHVibGljIHZvaWQgU2V0R2FtZU1vZGUoR2FtZU1vZGUgbW9kZSkKICAgIHsKICAgICAgICBjdXJyZW50TW9kZSA9IG1vZGU7CiAgICAgICAgRGVidWcuTG9nKCQi5ri45oiP5qih5byP5YiH5o2i6IezOiB7bW9kZX0iKTsKICAgIH0KICAgIAogICAgdm9pZCBIYW5kbGVQbGFjZW1lbnQoKQogICAgewogICAgICAgIFJheSByYXkgPSBwbGF5ZXJDYW1lcmEuU2NyZWVuUG9pbnRUb1JheShJbnB1dC5tb3VzZVBvc2l0aW9uKTsKICAgICAgICBSYXljYXN0SGl0IGhpdDsKICAgICAgICAKICAgICAgICBpZiAoUGh5c2ljcy5SYXljYXN0KHJheSwgb3V0IGhpdCwgTWF0aGYuSW5maW5pdHksIGdyb3VuZExheWVyKSkKICAgICAgICB7CiAgICAgICAgICAgIFZlY3RvcjMgcGxhY2VtZW50UG9zaXRpb24gPSBoaXQucG9pbnQ7CiAgICAgICAgICAgIAogICAgICAgICAgICBzd2l0Y2ggKGN1cnJlbnRNb2RlKQogICAgICAgICAgICB7CiAgICAgICAgICAgICAgICBjYXNlIEdhbWVNb2RlLlBsYW50VHJlZToKICAgICAgICAgICAgICAgICAgICBQbGFudFRyZWUocGxhY2VtZW50UG9zaXRpb24pOwogICAgICAgICAgICAgICAgICAgIGJyZWFrOwogICAgICAgICAgICAgICAgY2FzZSBHYW1lTW9kZS5CdWlsZDoKICAgICAgICAgICAgICAgICAgICBQbGFjZUJ1aWxkaW5nKHBsYWNlbWVudFBvc2l0aW9uKTsKICAgICAgICAgICAgICAgICAgICBicmVhazsKICAgICAgICAgICAgfQogICAgICAgIH0KICAgIH0KICAgIAogICAgdm9pZCBQbGFudFRyZWUoVmVjdG9yMyBwb3NpdGlvbikKICAgIHsKICAgICAgICBpZiAodHJlZVByZWZhYnMgIT0gbnVsbCAmJiB0cmVlUHJlZmFicy5MZW5ndGggPiAwKQogICAgICAgIHsKICAgICAgICAgICAgR2FtZU9iamVjdCBzZWxlY3RlZFRyZWUgPSB0cmVlUHJlZmFic1tSYW5kb20uUmFuZ2UoMCwgdHJlZVByZWZhYnMuTGVuZ3RoKV07CiAgICAgICAgICAgIGlmIChzZWxlY3RlZFRyZWUgIT0gbnVsbCkKICAgICAgICAgICAgewogICAgICAgICAgICAgICAgR2FtZU9iamVjdCBuZXdUcmVlID0gSW5zdGFudGlhdGUoc2VsZWN0ZWRUcmVlLCBwb3NpdGlvbiwgUXVhdGVybmlvbi5pZGVudGl0eSk7CiAgICAgICAgICAgICAgICAvLyDpmo/mnLrml4vovawKICAgICAgICAgICAgICAgIG5ld1RyZWUudHJhbnNmb3JtLnJvdGF0aW9uID0gUXVhdGVybmlvbi5FdWxlcigwLCBSYW5kb20uUmFuZ2UoMCwgMzYwKSwgMCk7CiAgICAgICAgICAgICAgICBEZWJ1Zy5Mb2coJCLlnKgge3Bvc2l0aW9ufSDnp43mpI3kuobkuIDmo7XmoJEiKTsKICAgICAgICAgICAgfQogICAgICAgIH0KICAgIH0KICAgIAogICAgdm9pZCBQbGFjZUJ1aWxkaW5nKFZlY3RvcjMgcG9zaXRpb24pCiAgICB7CiAgICAgICAgaWYgKGJ1aWxkaW5nUHJlZmFicyAhPSBudWxsICYmIGJ1aWxkaW5nUHJlZmFicy5MZW5ndGggPiAwKQogICAgICAgIHsKICAgICAgICAgICAgR2FtZU9iamVjdCBzZWxlY3RlZEJ1aWxkaW5nID0gYnVpbGRpbmdQcmVmYWJzW1JhbmRvbS5SYW5nZSgwLCBidWlsZGluZ1ByZWZhYnMuTGVuZ3RoKV07CiAgICAgICAgICAgIGlmIChzZWxlY3RlZEJ1aWxkaW5nICE9IG51bGwpCiAgICAgICAgICAgIHsKICAgICAgICAgICAgICAgIEdhbWVPYmplY3QgbmV3QnVpbGRpbmcgPSBJbnN0YW50aWF0ZShzZWxlY3RlZEJ1aWxkaW5nLCBwb3NpdGlvbiwgUXVhdGVybmlvbi5pZGVudGl0eSk7CiAgICAgICAgICAgICAgICBEZWJ1Zy5Mb2coJCLlnKgge3Bvc2l0aW9ufSDlu7rpgKDkuobkuIDkuKrlu7rnrZEiKTsKICAgICAgICAgICAgfQogICAgICAgIH0KICAgIH0KfQ==",
            "contentsEncoded": True,
            "x-canvas-id": "188c0c24-4fdb-4848-bb20-5423fcfb06f2",
            "x-seele-canvas-trace-id": "188c0c24-4fdb-4848-bb20-5423fcfb06f2|a9006edb-58c3-48ee-9e21-55cacb602f89|loop_flow-3cee09a8d09a72173b5d5c70|create_script_11db8116-a346-4d87-bf10-10de0a3858fd"
        }
    )
    print(res)


async def add_component():
    await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "add_component",
            "target": "GameController",
            "searchMethod": "by_name",
            "componentsToAdd": [
                "SimpleSnakeController"
            ],
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "1f52b9b7-1418-40e6-ac3f-00e6fc4c0919",
            "x-seele-canvas-trace-id": "1f52b9b7-1418-40e6-ac3f-00e6fc4c0919|fdadd025-6db2-4a40-8975-862cba21f841|loop_flow-a9d42bbb7494ea27deb85ec1|manage_gameobject_cbddc0f6-5276-42f9-9d4f-d8a85526791d"
        }
    )


async def add_perfab_component():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "modify",
            "name": "Bullet",
            "target": "Bullet",
            "searchMethod": "by_name",
            "componentsToAdd": [
                "Rigidbody",
                "Bullet"
            ],
            "saveAsPrefab": True,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "1f52b9b7-1418-40e6-ac3f-00e6fc4c0919",
            "x-seele-canvas-trace-id": "1f52b9b7-1418-40e6-ac3f-00e6fc4c0919|fdadd025-6db2-4a40-8975-862cba21f841|loop_flow-a9d42bbb7494ea27deb85ec1|manage_gameobject_cbddc0f6-5276-42f9-9d4f-d8a85526791d"
        }
    )
    print(res)


async def modify_component():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "modify",
            "target": "tank_1_1",
            "searchMethod": "by_name",
            "name": "EnemyTank",
            "tag": "Enemy",
            "position": [
                5.0,
                0.0,
                10.0
            ],
            "componentsToAdd": [
                "EnemyTankAI",
                "TankHealth"
            ],
            "saveAsPrefab": True,
            "prefabFolder": "Assets/Prefabs",
            "componentProperties": {
                "EnemyTankAI": {
                    "bulletPrefab": "Assets/Prefabs/Bullet.prefab"
                }
            },
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "be527fd0-08fe-40ad-a0d5-8b8827072b55",
            "x-seele-canvas-trace-id": "be527fd0-08fe-40ad-a0d5-8b8827072b55|70f98604-5ab6-47e7-ba32-8308ce8e89f5|loop_flow-8afb11bda199ba87c04d6888|manage_gameobject_b8014fab-6628-40eb-8e3a-d9fa59b801ab"
        }
    )
    print(res)


async def properties():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "modify",
            "target": "GameManager",
            "searchMethod": "by_name",
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "componentProperties": {
                "GameManager": {
                    "startPanel": {
                        "find": "StartPanel",
                        "method": "by_name"
                    },
                    "gameOverPanel": {
                        "find": "GameOverPanel",
                        "method": "by_name"
                    },
                    "scoreText": {
                        "find": "ScoreText",
                        "method": "by_name"
                    },
                    "instructionText": {
                        "find": "InstructionText",
                        "method": "by_name"
                    }
                }
            }
        }
    )
    print(res)

async def execute_fn():
    res = await get_current_connection().send_command(
        "manage_script",
        {
            "action": "execute",
            "main_function": "Main",
            "script_content": """
using System;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// 静态类：获取并打印当前场景名称到控制台
/// </summary>
public static class SceneInfoPrinter
{
    /// <summary>
    /// 主入口函数：获取当前场景名称并打印
    /// </summary>
    public static void Main()
    {
        try
        {
            // 获取当前激活的场景（Unity 运行时核心 API）
            Scene currentScene = SceneManager.GetActiveScene();
            
            // 场景名称（name：仅场景名；path：完整资源路径）
            string sceneName = currentScene.name;
            string scenePath = currentScene.path;

            // 打印到控制台（多信息维度，便于调试）
            Console.WriteLine("==================== 场景信息 ====================");
            Console.WriteLine($"当前激活场景名称：{sceneName}");
            Console.WriteLine($"场景完整路径：{scenePath}");
            Console.WriteLine($"场景是否已加载：{currentScene.isLoaded}");
            Console.WriteLine($"场景索引：{currentScene.buildIndex}");
            Console.WriteLine("==================================================");

            // 兼容 Unity 的 Debug 日志（同时输出到 Unity Console）
            Debug.Log($"[SceneInfoPrinter] 当前场景名称：{sceneName}");
        }
        catch (Exception ex)
        {
            // 异常捕获（避免空场景/未初始化等问题导致崩溃）
            Console.WriteLine($"获取场景名称失败：{ex.Message}");
            Debug.LogError($"[SceneInfoPrinter] 异常：{ex.Message}\n{ex.StackTrace}");
        }
    }
}""",
        }
    )
    print(res)

async def add_click():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "modify",
            "target": "StartButton",
            "searchMethod": "by_name",
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "componentProperties": {
                "Button": {
                    "onClick.m_PersistentCalls.m_Calls": [
                        {
                            "m_Target": {
                                "find": "GameManager",
                                "component": "FarmGameManager"
                            },
                            "m_MethodName": "StartGame",
                            "m_Mode": 1,
                            "m_CallState": 2
                        }
                    ]
                }
            },
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "2b08da7c-655e-424a-b22e-05b93e9cbede",
            "x-seele-canvas-trace-id": "2b08da7c-655e-424a-b22e-05b93e9cbede|38e120af-2546-474d-a9e1-26b2cc1e8147|loop_flow-7fc6866685efd67fea2c3586|manage_gameobject_18798ef1-b3af-466e-b3a0-8343ce573bcb",
            "trace_id": "34ce5b11"
        }
    )
    # res = await get_current_connection().send_command(
    #     "manage_gameobject",
    #     {
    #         "action": "modify",
    #         "target": "StartButton",
    #         "searchMethod": "by_name",
    #         "saveAsPrefab": False,
    #         "prefabFolder": "Assets/Prefabs",
    #         "componentProperties": {
    #             "Button": {
    #             "onClick": {
    #                 "target": {
    #                 "method": "by_name",
    #                 "find": "GameManager"
    #                 },
    #                 "methodName": "StartGameFromButton"
    #             }
    #             }
    #         },
    #         "findAll": False,
    #         "searchInChildren": False,
    #         "searchInactive": False,
    #         "x-canvas-id": "e44edd82-e450-4b9f-8a34-a149b515dae6",
    #         "x-seele-canvas-trace-id": "e44edd82-e450-4b9f-8a34-a149b515dae6|e4d908a0-8bf9-4c97-95ba-27360bd296a9|loop_flow-fb6f9c88404f772c7c7b89e2|manage_gameobject_0ee7b1b8-e985-4b1a-bf10-ab6b935532dd"
    #     }
    # )
    print(res)


async def create_canvas():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "create",
            "name": "Canvas",
            "componentsToAdd": [
                "Canvas"
            ],
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "aa681e28-17bf-455e-8142-3258278459d7",
            "x-seele-canvas-trace-id": "aa681e28-17bf-455e-8142-3258278459d7|5bc374f6-e33a-41f9-90c7-e729cc638de7|loop_flow-3ba006731c6e3a9942d6251e|manage_gameobject_08f99f5a-6353-49d0-849f-83249caa81f6"
        }
    )
    print(res)


async def read_script():
    res = await get_current_connection().send_command(
        "manage_script",
        {
            "action": "read",
            "name": "GameManager",
            "path": "Assets/Scripts"
        }
    )
    print(res)


async def textMeshProU():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "create",
            "name": "ScoreText",
            "parent": "StartPanel",
            "componentsToAdd": [
                "TextMeshProUGUI"
            ],
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "c0514565-cf5d-4fdb-a0f8-5be15379ed9b",
            "x-seele-canvas-trace-id": "c0514565-cf5d-4fdb-a0f8-5be15379ed9b|50341eda-0a68-4f4a-8f62-0e884caac998|loop_flow-bb4d7fd9c47fcfad32ff5e79|manage_gameobject_a0462777-5adc-4326-beb4-9f3d7634ffc0",
            "trace_id": "3a8d436e"
        }
    )
    print(res)


async def get_active_false_gameobject():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "get_components",
            "target": "RestartButton",
            "searchMethod": "by_name",
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9",
            "x-seele-canvas-trace-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9|f3a1d621-e9c9-40a2-81f5-0049142a8ed2|loop_flow-c64b068d0b4783da28cb94e7|manage_gameobject_318a8eab-22af-44cd-a79e-3af01b2de7eb",
            "trace_id": "a2822c88"
        }
    )
    print(res)


async def modify_active_false_gameobject():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        # {
        # "action": "modify",
        # "target": "WinPanel",
        # "searchMethod": "by_name",
        # "saveAsPrefab": False,
        # "prefabFolder": "Assets/Prefabs",
        # "setActive": True,
        # "findAll": False,
        # "searchInChildren": False,
        # "searchInactive": False,
        # "x-canvas-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9",
        # "x-seele-canvas-trace-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9|f3a1d621-e9c9-40a2-81f5-0049142a8ed2|loop_flow-c64b068d0b4783da28cb94e7|manage_gameobject_c926ff0c-bf22-46eb-b4a0-3f2f65e6642c",
        # "trace_id": "eb4cf8d6"
        # }

        {
            "action": "modify",
            "target": "GameManager",
            "searchMethod": "by_name",
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "componentProperties": {
                "GameManager": {
                    "player1": {
                        "find": "fighter1",
                        "method": "by_name"
                    },
                    "player2": {
                        "find": "fighter2",
                        "method": "by_name"
                    },
                    "player1HealthBar": {
                        "find": "Player1HealthBar",
                        "method": "by_name",
                        "component": "Slider"
                    },
                    "player2HealthBar": {
                        "find": "Player2HealthBar",
                        "method": "by_name",
                        "component": "Slider"
                    },
                    "gameOverText": {
                        "find": "GameOverText",
                        "method": "by_name",
                        "component": "TextMeshProUGUI"
                    },
                    "startPanel": {
                        "find": "StartPanel",
                        "method": "by_name"
                    },
                    "gameOverPanel": {
                        "find": "GameOverPanel",
                        "method": "by_name"
                    },
                    "startButton": {
                        "find": "StartButton",
                        "method": "by_name",
                        "component": "Button"
                    },
                    "restartButton": {
                        "find": "RestartButton",
                        "method": "by_name",
                        "component": "Button"
                    },
                    "controlsText": {
                        "find": "ControlsText",
                        "method": "by_name",
                        "component": "TextMeshProUGUI"
                    }
                }
            },
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": False,
            "x-canvas-id": "2f563714-7624-4888-9e63-c876208d90d9",
            "x-seele-canvas-trace-id": "2f563714-7624-4888-9e63-c876208d90d9|8fc3b396-d633-49ab-a277-4e0c1b6ff6ed|loop_flow-7a3f9319d408915f81cb8924|manage_gameobject_ef74a767-462a-4632-962d-14df422e33c5",
            "trace_id": "31f802ce"
        }
    )
    formatted_json = json.dumps(
        res, indent=4, ensure_ascii=False, sort_keys=False)
    print(formatted_json)


async def get_info():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "get_components",
            "target": "GameManager",
            "searchMethod": "by_name",
            "x-canvas-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9",
            "x-seele-canvas-trace-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9|f3a1d621-e9c9-40a2-81f5-0049142a8ed2|loop_flow-c64b068d0b4783da28cb94e7|manage_gameobject_c926ff0c-bf22-46eb-b4a0-3f2f65e6642c",
            "trace_id": "eb4cf8d6"
        }
    )
    print(res)


async def get_children():
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "find",
            "target": "Text3",
            "searchInChildren": False,
            "searchMethod": "by_name",
            "x-canvas-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9",
            "x-seele-canvas-trace-id": "ddec525d-cef9-4f7d-8f52-7214279aceb9|f3a1d621-e9c9-40a2-81f5-0049142a8ed2|loop_flow-c64b068d0b4783da28cb94e7|manage_gameobject_c926ff0c-bf22-46eb-b4a0-3f2f65e6642c",
            "trace_id": "eb4cf8d6"
        }
    )
    print(res)


async def create_gameobject_add_component():
    # scriptres = await get_current_connection().send_command(
    #     "manage_script",
    #     {
    #         "action": "create",
    #         "name": "ChessPieceData",
    #         "path": "Assets/Scripts",
    #         "encodedContents": "dXNpbmcgVW5pdHlFbmdpbmU7CnVzaW5nIFN5c3RlbS5Db2xsZWN0aW9ucy5HZW5lcmljOwoKcHVibGljIGVudW0gUGllY2VDbGFzcwp7CiAgICBXYXJyaW9yLCAgICAvLyDmiJjlo6sKICAgIE1hZ2UsICAgICAgIC8vIOazleW4iAogICAgQXNzYXNzaW4sICAgLy8g5Yi65a6iCiAgICBSYW5nZXIsICAgICAvLyDlsITmiYsKICAgIFRhbmssICAgICAgIC8vIOWdpuWFiwogICAgU3VwcG9ydCAgICAgLy8g6L6F5YqpCn0KCnB1YmxpYyBlbnVtIFBpZWNlUmFjZQp7CiAgICBIdW1hbiwgICAgICAvLyDkurrnsbsKICAgIE9yYywgICAgICAgIC8vIOWFveS6ugogICAgRWxmLCAgICAgICAgLy8g57K+54G1CiAgICBVbmRlYWQsICAgICAvLyDkuqHngbUKICAgIERyYWdvbiwgICAgIC8vIOm+meaXjwogICAgRGVtb24gICAgICAgLy8g5oG26a2UCn0KCltTeXN0ZW0uU2VyaWFsaXphYmxlXQpwdWJsaWMgY2xhc3MgQ2hlc3NQaWVjZURhdGEKewogICAgcHVibGljIHN0cmluZyBwaWVjZU5hbWU7CiAgICBwdWJsaWMgUGllY2VDbGFzcyBwaWVjZUNsYXNzOwogICAgcHVibGljIFBpZWNlUmFjZSBwaWVjZVJhY2U7CiAgICBwdWJsaWMgaW50IGNvc3Q7CiAgICBwdWJsaWMgaW50IHN0YXI7CiAgICAKICAgIC8vIOWfuuehgOWxnuaApwogICAgcHVibGljIGZsb2F0IGhlYWx0aDsKICAgIHB1YmxpYyBmbG9hdCBhdHRhY2s7CiAgICBwdWJsaWMgZmxvYXQgYXR0YWNrU3BlZWQ7CiAgICBwdWJsaWMgZmxvYXQgYXR0YWNrUmFuZ2U7CiAgICBwdWJsaWMgZmxvYXQgbW92ZVNwZWVkOwogICAgcHVibGljIGZsb2F0IGFybW9yOwogICAgcHVibGljIGZsb2F0IG1hZ2ljUmVzaXN0OwogICAgCiAgICAvLyDmioDog70KICAgIHB1YmxpYyBzdHJpbmcgc2tpbGxOYW1lOwogICAgcHVibGljIHN0cmluZyBza2lsbERlc2NyaXB0aW9uOwogICAgcHVibGljIGZsb2F0IHNraWxsRGFtYWdlOwogICAgcHVibGljIGZsb2F0IHNraWxsQ29vbGRvd247CiAgICAKICAgIHB1YmxpYyBDb2xvciBwaWVjZUNvbG9yOwogICAgCiAgICBwdWJsaWMgQ2hlc3NQaWVjZURhdGEgQ2xvbmUoKQogICAgewogICAgICAgIHJldHVybiBuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9IHRoaXMucGllY2VOYW1lLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gdGhpcy5waWVjZUNsYXNzLAogICAgICAgICAgICBwaWVjZVJhY2UgPSB0aGlzLnBpZWNlUmFjZSwKICAgICAgICAgICAgY29zdCA9IHRoaXMuY29zdCwKICAgICAgICAgICAgc3RhciA9IHRoaXMuc3RhciwKICAgICAgICAgICAgaGVhbHRoID0gdGhpcy5oZWFsdGgsCiAgICAgICAgICAgIGF0dGFjayA9IHRoaXMuYXR0YWNrLAogICAgICAgICAgICBhdHRhY2tTcGVlZCA9IHRoaXMuYXR0YWNrU3BlZWQsCiAgICAgICAgICAgIGF0dGFja1JhbmdlID0gdGhpcy5hdHRhY2tSYW5nZSwKICAgICAgICAgICAgbW92ZVNwZWVkID0gdGhpcy5tb3ZlU3BlZWQsCiAgICAgICAgICAgIGFybW9yID0gdGhpcy5hcm1vciwKICAgICAgICAgICAgbWFnaWNSZXNpc3QgPSB0aGlzLm1hZ2ljUmVzaXN0LAogICAgICAgICAgICBza2lsbE5hbWUgPSB0aGlzLnNraWxsTmFtZSwKICAgICAgICAgICAgc2tpbGxEZXNjcmlwdGlvbiA9IHRoaXMuc2tpbGxEZXNjcmlwdGlvbiwKICAgICAgICAgICAgc2tpbGxEYW1hZ2UgPSB0aGlzLnNraWxsRGFtYWdlLAogICAgICAgICAgICBza2lsbENvb2xkb3duID0gdGhpcy5za2lsbENvb2xkb3duLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gdGhpcy5waWVjZUNvbG9yCiAgICAgICAgfTsKICAgIH0KfQoKcHVibGljIGNsYXNzIFBpZWNlRGF0YWJhc2UgOiBNb25vQmVoYXZpb3VyCnsKICAgIHB1YmxpYyBzdGF0aWMgUGllY2VEYXRhYmFzZSBJbnN0YW5jZSB7IGdldDsgcHJpdmF0ZSBzZXQ7IH0KICAgIAogICAgcHJpdmF0ZSBMaXN0PENoZXNzUGllY2VEYXRhPiBhbGxQaWVjZXMgPSBuZXcgTGlzdDxDaGVzc1BpZWNlRGF0YT4oKTsKICAgIAogICAgdm9pZCBBd2FrZSgpCiAgICB7CiAgICAgICAgaWYgKEluc3RhbmNlID09IG51bGwpCiAgICAgICAgewogICAgICAgICAgICBJbnN0YW5jZSA9IHRoaXM7CiAgICAgICAgICAgIEluaXRpYWxpemVQaWVjZXMoKTsKICAgICAgICB9CiAgICAgICAgZWxzZQogICAgICAgIHsKICAgICAgICAgICAgRGVzdHJveShnYW1lT2JqZWN0KTsKICAgICAgICB9CiAgICB9CiAgICAKICAgIHZvaWQgSW5pdGlhbGl6ZVBpZWNlcygpCiAgICB7CiAgICAgICAgLy8gMei0ueaji+WtkAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5YmR5aOrIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuV2FycmlvciwKICAgICAgICAgICAgcGllY2VSYWNlID0gUGllY2VSYWNlLkh1bWFuLAogICAgICAgICAgICBjb3N0ID0gMSwKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDYwMCwKICAgICAgICAgICAgYXR0YWNrID0gNTAsCiAgICAgICAgICAgIGF0dGFja1NwZWVkID0gMS4wZiwKICAgICAgICAgICAgYXR0YWNrUmFuZ2UgPSAxLjVmLAogICAgICAgICAgICBtb3ZlU3BlZWQgPSAyLjBmLAogICAgICAgICAgICBhcm1vciA9IDUsCiAgICAgICAgICAgIG1hZ2ljUmVzaXN0ID0gMCwKICAgICAgICAgICAgc2tpbGxOYW1lID0gIuaXi+mjjuaWqSIsCiAgICAgICAgICAgIHNraWxsRGVzY3JpcHRpb24gPSAi5a+55ZGo5Zu05pWM5Lq66YCg5oiQ5Lyk5a6zIiwKICAgICAgICAgICAgc2tpbGxEYW1hZ2UgPSAxNTAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSA4ZiwKICAgICAgICAgICAgcGllY2VDb2xvciA9IG5ldyBDb2xvcigwLjhmLCAwLjZmLCAwLjRmKQogICAgICAgIH0pOwogICAgICAgIAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5byT566t5omLIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuUmFuZ2VyLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuRWxmLAogICAgICAgICAgICBjb3N0ID0gMSwKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDQ1MCwKICAgICAgICAgICAgYXR0YWNrID0gNDUsCiAgICAgICAgICAgIGF0dGFja1NwZWVkID0gMS4yZiwKICAgICAgICAgICAgYXR0YWNrUmFuZ2UgPSA0LjBmLAogICAgICAgICAgICBtb3ZlU3BlZWQgPSAyLjJmLAogICAgICAgICAgICBhcm1vciA9IDAsCiAgICAgICAgICAgIG1hZ2ljUmVzaXN0ID0gMCwKICAgICAgICAgICAgc2tpbGxOYW1lID0gIuepv+WIuueurSIsCiAgICAgICAgICAgIHNraWxsRGVzY3JpcHRpb24gPSAi5Y+R5bCE56m/5Yi6566t55+iIiwKICAgICAgICAgICAgc2tpbGxEYW1hZ2UgPSAxMjAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSA2ZiwKICAgICAgICAgICAgcGllY2VDb2xvciA9IG5ldyBDb2xvcigwLjRmLCAwLjhmLCAwLjRmKQogICAgICAgIH0pOwogICAgICAgIAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5YW95Lq65YuH5aOrIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuVGFuaywKICAgICAgICAgICAgcGllY2VSYWNlID0gUGllY2VSYWNlLk9yYywKICAgICAgICAgICAgY29zdCA9IDEsCiAgICAgICAgICAgIHN0YXIgPSAxLAogICAgICAgICAgICBoZWFsdGggPSA3MDAsCiAgICAgICAgICAgIGF0dGFjayA9IDQwLAogICAgICAgICAgICBhdHRhY2tTcGVlZCA9IDAuOWYsCiAgICAgICAgICAgIGF0dGFja1JhbmdlID0gMS41ZiwKICAgICAgICAgICAgbW92ZVNwZWVkID0gMS44ZiwKICAgICAgICAgICAgYXJtb3IgPSAxMCwKICAgICAgICAgICAgbWFnaWNSZXNpc3QgPSA1LAogICAgICAgICAgICBza2lsbE5hbWUgPSAi5oiY5ZC8IiwKICAgICAgICAgICAgc2tpbGxEZXNjcmlwdGlvbiA9ICLmj5DljYflkajlm7Tlj4vlhpvmlLvlh7vlipsiLAogICAgICAgICAgICBza2lsbERhbWFnZSA9IDAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSAxMGYsCiAgICAgICAgICAgIHBpZWNlQ29sb3IgPSBuZXcgQ29sb3IoMC42ZiwgMC4zZiwgMC4yZikKICAgICAgICB9KTsKICAgICAgICAKICAgICAgICAvLyAy6LS55qOL5a2QCiAgICAgICAgYWxsUGllY2VzLkFkZChuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9ICLngavnhLDms5XluIgiLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gUGllY2VDbGFzcy5NYWdlLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuSHVtYW4sCiAgICAgICAgICAgIGNvc3QgPSAyLAogICAgICAgICAgICBzdGFyID0gMSwKICAgICAgICAgICAgaGVhbHRoID0gNTAwLAogICAgICAgICAgICBhdHRhY2sgPSA2MCwKICAgICAgICAgICAgYXR0YWNrU3BlZWQgPSAxLjVmLAogICAgICAgICAgICBhdHRhY2tSYW5nZSA9IDMuNWYsCiAgICAgICAgICAgIG1vdmVTcGVlZCA9IDIuMGYsCiAgICAgICAgICAgIGFybW9yID0gMCwKICAgICAgICAgICAgbWFnaWNSZXNpc3QgPSAxMCwKICAgICAgICAgICAgc2tpbGxOYW1lID0gIueBq+eQg+acryIsCiAgICAgICAgICAgIHNraWxsRGVzY3JpcHRpb24gPSAi5Y+R5bCE54Gr55CD6YCg5oiQ6IyD5Zu05Lyk5a6zIiwKICAgICAgICAgICAgc2tpbGxEYW1hZ2UgPSAyNTAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSA3ZiwKICAgICAgICAgICAgcGllY2VDb2xvciA9IG5ldyBDb2xvcigxLjBmLCAwLjNmLCAwLjFmKQogICAgICAgIH0pOwogICAgICAgIAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5pqX5b2x5Yi65a6iIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuQXNzYXNzaW4sCiAgICAgICAgICAgIHBpZWNlUmFjZSA9IFBpZWNlUmFjZS5VbmRlYWQsCiAgICAgICAgICAgIGNvc3QgPSAyLAogICAgICAgICAgICBzdGFyID0gMSwKICAgICAgICAgICAgaGVhbHRoID0gNTUwLAogICAgICAgICAgICBhdHRhY2sgPSA3MCwKICAgICAgICAgICAgYXR0YWNrU3BlZWQgPSAxLjRmLAogICAgICAgICAgICBhdHRhY2tSYW5nZSA9IDEuNWYsCiAgICAgICAgICAgIG1vdmVTcGVlZCA9IDIuNWYsCiAgICAgICAgICAgIGFybW9yID0gMywKICAgICAgICAgICAgbWFnaWNSZXNpc3QgPSAzLAogICAgICAgICAgICBza2lsbE5hbWUgPSAi6IOM5Yi6IiwKICAgICAgICAgICAgc2tpbGxEZXNjcmlwdGlvbiA9ICLnnqznp7vliLDmlYzkurrog4zlkI7pgKDmiJDmmrTlh7siLAogICAgICAgICAgICBza2lsbERhbWFnZSA9IDMwMCwKICAgICAgICAgICAgc2tpbGxDb29sZG93biA9IDlmLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gbmV3IENvbG9yKDAuM2YsIDAuMWYsIDAuNGYpCiAgICAgICAgfSk7CiAgICAgICAgCiAgICAgICAgLy8gM+i0ueaji+WtkAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5Zyj6aqR5aOrIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuVGFuaywKICAgICAgICAgICAgcGllY2VSYWNlID0gUGllY2VSYWNlLkh1bWFuLAogICAgICAgICAgICBjb3N0ID0gMywKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDkwMCwKICAgICAgICAgICAgYXR0YWNrID0gNTUsCiAgICAgICAgICAgIGF0dGFja1NwZWVkID0gMS4wZiwKICAgICAgICAgICAgYXR0YWNrUmFuZ2UgPSAxLjVmLAogICAgICAgICAgICBtb3ZlU3BlZWQgPSAxLjlmLAogICAgICAgICAgICBhcm1vciA9IDE1LAogICAgICAgICAgICBtYWdpY1Jlc2lzdCA9IDE1LAogICAgICAgICAgICBza2lsbE5hbWUgPSAi5Zyj5YWJ5oqk55u+IiwKICAgICAgICAgICAgc2tpbGxEZXNjcmlwdGlvbiA9ICLojrflvpfmiqTnm77lubblmLLorr3mlYzkuroiLAogICAgICAgICAgICBza2lsbERhbWFnZSA9IDAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSAxMmYsCiAgICAgICAgICAgIHBpZWNlQ29sb3IgPSBuZXcgQ29sb3IoMS4wZiwgMC45ZiwgMC42ZikKICAgICAgICB9KTsKICAgICAgICAKICAgICAgICBhbGxQaWVjZXMuQWRkKG5ldyBDaGVzc1BpZWNlRGF0YQogICAgICAgIHsKICAgICAgICAgICAgcGllY2VOYW1lID0gIueyvueBtea4uOS+oCIsCiAgICAgICAgICAgIHBpZWNlQ2xhc3MgPSBQaWVjZUNsYXNzLlJhbmdlciwKICAgICAgICAgICAgcGllY2VSYWNlID0gUGllY2VSYWNlLkVsZiwKICAgICAgICAgICAgY29zdCA9IDMsCiAgICAgICAgICAgIHN0YXIgPSAxLAogICAgICAgICAgICBoZWFsdGggPSA2MDAsCiAgICAgICAgICAgIGF0dGFjayA9IDY1LAogICAgICAgICAgICBhdHRhY2tTcGVlZCA9IDEuNWYsCiAgICAgICAgICAgIGF0dGFja1JhbmdlID0gNC41ZiwKICAgICAgICAgICAgbW92ZVNwZWVkID0gMi4zZiwKICAgICAgICAgICAgYXJtb3IgPSA1LAogICAgICAgICAgICBtYWdpY1Jlc2lzdCA9IDEwLAogICAgICAgICAgICBza2lsbE5hbWUgPSAi5aSa6YeN5bCE5Ye7IiwKICAgICAgICAgICAgc2tpbGxEZXNjcmlwdGlvbiA9ICLlkIzml7bmlLvlh7vlpJrkuKrnm67moIciLAogICAgICAgICAgICBza2lsbERhbWFnZSA9IDE4MCwKICAgICAgICAgICAgc2tpbGxDb29sZG93biA9IDhmLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gbmV3IENvbG9yKDAuMmYsIDAuOWYsIDAuNmYpCiAgICAgICAgfSk7CiAgICAgICAgCiAgICAgICAgYWxsUGllY2VzLkFkZChuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9ICLlhrDpnJzlt6vluIgiLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gUGllY2VDbGFzcy5NYWdlLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuRWxmLAogICAgICAgICAgICBjb3N0ID0gMywKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDU1MCwKICAgICAgICAgICAgYXR0YWNrID0gNzAsCiAgICAgICAgICAgIGF0dGFja1NwZWVkID0gMS42ZiwKICAgICAgICAgICAgYXR0YWNrUmFuZ2UgPSAzLjVmLAogICAgICAgICAgICBtb3ZlU3BlZWQgPSAyLjBmLAogICAgICAgICAgICBhcm1vciA9IDAsCiAgICAgICAgICAgIG1hZ2ljUmVzaXN0ID0gMTUsCiAgICAgICAgICAgIHNraWxsTmFtZSA9ICLlhrDpnJzmlrDmmJ8iLAogICAgICAgICAgICBza2lsbERlc2NyaXB0aW9uID0gIuWGsOWGu+W5tuS8pOWus+WRqOWbtOaVjOS6uiIsCiAgICAgICAgICAgIHNraWxsRGFtYWdlID0gMzAwLAogICAgICAgICAgICBza2lsbENvb2xkb3duID0gMTBmLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gbmV3IENvbG9yKDAuM2YsIDAuNmYsIDEuMGYpCiAgICAgICAgfSk7CiAgICAgICAgCiAgICAgICAgLy8gNOi0ueaji+WtkAogICAgICAgIGFsbFBpZWNlcy5BZGQobmV3IENoZXNzUGllY2VEYXRhCiAgICAgICAgewogICAgICAgICAgICBwaWVjZU5hbWUgPSAi5oG26a2U54yO5omLIiwKICAgICAgICAgICAgcGllY2VDbGFzcyA9IFBpZWNlQ2xhc3MuQXNzYXNzaW4sCiAgICAgICAgICAgIHBpZWNlUmFjZSA9IFBpZWNlUmFjZS5EZW1vbiwKICAgICAgICAgICAgY29zdCA9IDQsCiAgICAgICAgICAgIHN0YXIgPSAxLAogICAgICAgICAgICBoZWFsdGggPSA3NTAsCiAgICAgICAgICAgIGF0dGFjayA9IDkwLAogICAgICAgICAgICBhdHRhY2tTcGVlZCA9IDEuNmYsCiAgICAgICAgICAgIGF0dGFja1JhbmdlID0gMi4wZiwKICAgICAgICAgICAgbW92ZVNwZWVkID0gMi42ZiwKICAgICAgICAgICAgYXJtb3IgPSA4LAogICAgICAgICAgICBtYWdpY1Jlc2lzdCA9IDgsCiAgICAgICAgICAgIHNraWxsTmFtZSA9ICLmgbbprZTkuYvlipsiLAogICAgICAgICAgICBza2lsbERlc2NyaXB0aW9uID0gIuWPmOi6q+W5tuaPkOWNh+aUu+WHu+WKmyIsCiAgICAgICAgICAgIHNraWxsRGFtYWdlID0gNDAwLAogICAgICAgICAgICBza2lsbENvb2xkb3duID0gMTFmLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gbmV3IENvbG9yKDAuOGYsIDAuMWYsIDAuMmYpCiAgICAgICAgfSk7CiAgICAgICAgCiAgICAgICAgYWxsUGllY2VzLkFkZChuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9ICLpm7fnlLXokKjmu6EiLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gUGllY2VDbGFzcy5NYWdlLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuT3JjLAogICAgICAgICAgICBjb3N0ID0gNCwKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDY1MCwKICAgICAgICAgICAgYXR0YWNrID0gODUsCiAgICAgICAgICAgIGF0dGFja1NwZWVkID0gMS43ZiwKICAgICAgICAgICAgYXR0YWNrUmFuZ2UgPSAzLjBmLAogICAgICAgICAgICBtb3ZlU3BlZWQgPSAyLjBmLAogICAgICAgICAgICBhcm1vciA9IDUsCiAgICAgICAgICAgIG1hZ2ljUmVzaXN0ID0gMjAsCiAgICAgICAgICAgIHNraWxsTmFtZSA9ICLov57plIHpl6rnlLUiLAogICAgICAgICAgICBza2lsbERlc2NyaXB0aW9uID0gIumXqueUteWcqOaVjOS6uumXtOi3s+i3gyIsCiAgICAgICAgICAgIHNraWxsRGFtYWdlID0gMzUwLAogICAgICAgICAgICBza2lsbENvb2xkb3duID0gOWYsCiAgICAgICAgICAgIHBpZWNlQ29sb3IgPSBuZXcgQ29sb3IoMC40ZiwgMC40ZiwgMS4wZikKICAgICAgICB9KTsKICAgICAgICAKICAgICAgICAvLyA16LS55qOL5a2QCiAgICAgICAgYWxsUGllY2VzLkFkZChuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9ICLpvpnpqpHlo6siLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gUGllY2VDbGFzcy5XYXJyaW9yLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuRHJhZ29uLAogICAgICAgICAgICBjb3N0ID0gNSwKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDEyMDAsCiAgICAgICAgICAgIGF0dGFjayA9IDEwMCwKICAgICAgICAgICAgYXR0YWNrU3BlZWQgPSAxLjJmLAogICAgICAgICAgICBhdHRhY2tSYW5nZSA9IDIuMGYsCiAgICAgICAgICAgIG1vdmVTcGVlZCA9IDIuMmYsCiAgICAgICAgICAgIGFybW9yID0gMjAsCiAgICAgICAgICAgIG1hZ2ljUmVzaXN0ID0gMjAsCiAgICAgICAgICAgIHNraWxsTmFtZSA9ICLpvpnkuYvlkJDmga8iLAogICAgICAgICAgICBza2lsbERlc2NyaXB0aW9uID0gIuWWt+WwhOeDiOeEsOmAoOaIkOW3qOmineS8pOWusyIsCiAgICAgICAgICAgIHNraWxsRGFtYWdlID0gNjAwLAogICAgICAgICAgICBza2lsbENvb2xkb3duID0gMTJmLAogICAgICAgICAgICBwaWVjZUNvbG9yID0gbmV3IENvbG9yKDAuOWYsIDAuMmYsIDAuMWYpCiAgICAgICAgfSk7CiAgICAgICAgCiAgICAgICAgYWxsUGllY2VzLkFkZChuZXcgQ2hlc3NQaWVjZURhdGEKICAgICAgICB7CiAgICAgICAgICAgIHBpZWNlTmFtZSA9ICLlt6vlppbnjosiLAogICAgICAgICAgICBwaWVjZUNsYXNzID0gUGllY2VDbGFzcy5NYWdlLAogICAgICAgICAgICBwaWVjZVJhY2UgPSBQaWVjZVJhY2UuVW5kZWFkLAogICAgICAgICAgICBjb3N0ID0gNSwKICAgICAgICAgICAgc3RhciA9IDEsCiAgICAgICAgICAgIGhlYWx0aCA9IDgwMCwKICAgICAgICAgICAgYXR0YWNrID0gMTEwLAogICAgICAgICAgICBhdHRhY2tTcGVlZCA9IDIuMGYsCiAgICAgICAgICAgIGF0dGFja1JhbmdlID0gNC4wZiwKICAgICAgICAgICAgbW92ZVNwZWVkID0gMi4wZiwKICAgICAgICAgICAgYXJtb3IgPSAxMCwKICAgICAgICAgICAgbWFnaWNSZXNpc3QgPSAzMCwKICAgICAgICAgICAgc2tpbGxOYW1lID0gIuatu+S6oeWHi+mbtiIsCiAgICAgICAgICAgIHNraWxsRGVzY3JpcHRpb24gPSAi5Y+s5ZSk5Lqh54G15aSn5YabIiwKICAgICAgICAgICAgc2tpbGxEYW1hZ2UgPSA3MDAsCiAgICAgICAgICAgIHNraWxsQ29vbGRvd24gPSAxNWYsCiAgICAgICAgICAgIHBpZWNlQ29sb3IgPSBuZXcgQ29sb3IoMC4yZiwgMC44ZiwgMC4zZikKICAgICAgICB9KTsKICAgIH0KICAgIAogICAgcHVibGljIExpc3Q8Q2hlc3NQaWVjZURhdGE+IEdldFBpZWNlc0J5Q29zdChpbnQgY29zdCkKICAgIHsKICAgICAgICByZXR1cm4gYWxsUGllY2VzLkZpbmRBbGwocCA9PiBwLmNvc3QgPT0gY29zdCk7CiAgICB9CiAgICAKICAgIHB1YmxpYyBDaGVzc1BpZWNlRGF0YSBHZXRSYW5kb21QaWVjZShpbnQgY29zdCkKICAgIHsKICAgICAgICB2YXIgcGllY2VzID0gR2V0UGllY2VzQnlDb3N0KGNvc3QpOwogICAgICAgIGlmIChwaWVjZXMuQ291bnQgPiAwKQogICAgICAgIHsKICAgICAgICAgICAgcmV0dXJuIHBpZWNlc1tSYW5kb20uUmFuZ2UoMCwgcGllY2VzLkNvdW50KV0uQ2xvbmUoKTsKICAgICAgICB9CiAgICAgICAgcmV0dXJuIG51bGw7CiAgICB9CiAgICAKICAgIHB1YmxpYyBMaXN0PENoZXNzUGllY2VEYXRhPiBHZXRBbGxQaWVjZXMoKQogICAgewogICAgICAgIHJldHVybiBhbGxQaWVjZXM7CiAgICB9Cn0=", "contentsEncoded": true, "x-canvas-id": "e4a68b35-49ba-4151-8eeb-ac56902a8847", "x-seele-canvas-trace-id": "e4a68b35-49ba-4151-8eeb-ac56902a8847|85bcc9a3-f1cf-44a3-b05d-e69977875dc1|loop_flow-47aa160b9d0b764212195aef|create_script_1c2591c8-baf2-435e-8c4f-783ae733c2e7",
    #         "trace_id": "64b3096b"
    #     }
    # )
    # print(scriptres)
    res = await get_current_connection().send_command(
        "manage_gameobject",
        {
            "action": "create",
            "name": "PieceDatabase",
            "componentsToAdd": ["PieceDatabase"],
            "saveAsPrefab": False,
            "prefabFolder": "Assets/Prefabs",
            "findAll": False,
            "searchInChildren": False,
            "searchInactive": True,
            "x-canvas-id": "e4a68b35-49ba-4151-8eeb-ac56902a8847",
            "x-seele-canvas-trace-id": "e4a68b35-49ba-4151-8eeb-ac56902a8847|85bcc9a3-f1cf-44a3-b05d-e69977875dc1|loop_flow-47aa160b9d0b764212195aef|manage_gameobject_72696680-6b77-46d7-9288-d6b9eebd59c2",
            "trace_id": "8fcdb610"
        }
    )
    print(res)

if __name__ == "__main__":
    from async_http.http_register_manager import http_register_manager
    http_register_manager.start()
    asyncio.run(execute_fn())
