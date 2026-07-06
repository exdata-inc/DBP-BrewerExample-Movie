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


def apply_variables(data: dict, variables: dict) -> dict:
    for key, value in data.items():
        if key == "dbp:variables" and isinstance(value, dict):
            variables.update(data.get("dbp:variables") or {})

    if variables:
        for key, value in data.items():
            value_str = json.dumps(value)
            for var_key, var_value in variables.items():
                value_str = value_str.replace(r"{{" + f"{var_key}" + r"}}", str(var_value))
            data[key] = json.loads(value_str)

    for key, value in data.items():
        if isinstance(value, dict):
            data[key] = apply_variables(value, variables)
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    data[key][i] = apply_variables(item, variables)

    return data


async def fetch_brewing_demands_json(url: str, depth: int = 6):
    if url.startswith("http"):
        initial_response = await fetch_data(url)
        initial_json_data = json.loads(initial_response)
    else:
        initial_json_data = json.loads(url)
    final_result = await fetch_nested_data(initial_json_data, depth)
    final_result = apply_variables(final_result, {})
    return final_result
