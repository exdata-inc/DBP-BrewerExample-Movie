import httpx
import json


async def fetch_data(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text


async def fetch_nested_data(data, current_depth):
    if current_depth == 0:
        return data

    if isinstance(data, dict):
        result = data.copy()

        for key, value in data.items():
            if isinstance(value, dict) and "@id" in value:
                try:
                    if value["@id"].startswith("http"):
                        response = await fetch_data(value["@id"])
                        nested_json_data = json.loads(response)
                        result[key] = nested_json_data
                        nested_result = await fetch_nested_data(nested_json_data, current_depth - 1)
                        result[key] = nested_result
                except Exception as e:
                    print(f"Error: {e}")

            elif isinstance(value, list):
                result[key] = []
                for item in value:
                    if isinstance(item, dict) and "@id" in item:
                        try:
                            if item["@id"].startswith("http"):
                                response = await fetch_data(item["@id"])
                                nested_json_data = json.loads(response)
                                nested_result = await fetch_nested_data(nested_json_data, current_depth - 1)
                                result[key].append(nested_result)
                        except Exception as e:
                            print(f"Error: {e}")
                            result[key].append(item)
                    else:
                        result[key].append(item)
        return result
    return data


async def fetch_brewing_demands_json(url: str, depth: int = 6):
    initial_response = await fetch_data(url)
    initial_json_data = json.loads(initial_response)
    final_result = await fetch_nested_data(initial_json_data, depth)
    return final_result
