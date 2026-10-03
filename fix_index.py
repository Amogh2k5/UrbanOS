import sys
sys.path.insert(0, r'C:\projects\UrbanOS')

with open(r'C:\projects\UrbanOS\frontend\src\services\api\index.ts', 'rb') as f:
    content = f.read()

idx = content.find(b'// Types for overview')
if idx >= 0:
    prefix = content[:idx]
    
    new_types = b''.join([
        b'// Types for overview\n',
        b'export interface ModuleKPI {\n',
        b'  label: string;\n',
        b'  value: any;\n',
        b'  unit: string;\n',
        b'}\n\n',
        b'export interface ModuleSummary {\n',
        b'  id: string;\n',
        b'  name: string;\n',
        b'  status: "normal" | "elevated" | "critical" | "unavailable";\n',
        b'  kpi: ModuleKPI | null;\n',
        b'  updated_at: string | null;\n',
        b'  detail_route: string;\n',
        b'}\n\n',
        b'export interface AlertItem {\n',
        b'  domain: string;\n',
        b'  severity: string;\n',
        b'  title: string;\n',
        b'  description: string;\n',
        b'  timestamp: string;\n',
        b'  affected_zones: string[];\n',
        b'}\n\n',
        b'export interface OverviewCityResponse {\n',
        b'  generated_at: string;\n',
        b'  modules: ModuleSummary[];\n',
        b'  alerts: AlertItem[];\n',
        b'  ai_brief: string | null;\n',
        b'}\n\n',
        b'export interface ModuleDetailResponse {\n',
        b'  module_id: string;\n',
        b'  module_name: string;\n',
        b'  status: string;\n',
        b'  kpi: ModuleKPI | null;\n',
        b'  updated_at: string | null;\n',
        b'  summary: string;\n',
        b'  alerts: AlertItem[];\n',
        b'  cross_domain: string[];\n',
        b'  detail_route: string;\n',
        b'}\n\n',
        b'export interface ChatRequest {\n',
        b'  message: string;\n',
        b'  module_id?: string;\n',
        b'}\n\n',
        b'export interface ChatResponse {\n',
        b'  response: string;\n',
        b'}\n\n',
        b'// Overview API functions\n',
        b'export async function fetchOverviewCity(): Promise<any> {\n',
        b'  const response = await fetch(`${API_BASE}/api/overview/city`, { cache: \'no-store\'});\n',
        b'  if (!response.ok) {\n',
        b'    throw new Error(`Failed to fetch overview city: ${response.statusText}`);\n',
        b'  }\n',
        b'  return response.json();\n',
        b'}\n\n',
        b'export async function fetchOverviewModule(moduleId: string): Promise<any> {\n',
        b'  const response = await fetch(`${API_BASE}/api/overview/module/${moduleId}`, { cache: \'no-store\'});\n',
        b'  if (!response.ok) {\n',
        b'    throw new Error(`Failed to fetch overview module ${moduleId}: ${response.statusText}`);\n',
        b'  }\n',
        b'  return response.json();\n',
        b'}\n\n',
        b'export async function fetchChat(message: string, moduleId?: string): Promise<any> {\n',
        b'  const controller = new AbortController();\n',
        b'  const timeoutId = setTimeout(() => controller.abort(), 30_000);\n',
        b'  const url = new URL(`${API_BASE}/api/overview/chat`);\n',
        b'  try {\n',
        b'    const response = await fetch(url.toString(), {\n',
        b'      method: "POST",\n',
        b'      headers: { "Content-Type": "application/json" },\n',
        b'      body: JSON.stringify({ message, module_id: moduleId }),\n',
        b'      cache: "no-store",\n',
        b'      signal: controller.signal,\n',
        b'    });\n',
        b'    if (!response.ok) {\n',
        b'      let detail = response.statusText;\n',
        b'      try { const errJson = await response.json(); if (errJson?.detail) detail = errJson.detail; } catch {}\n',
        b'      throw new Error(`Failed to fetch chat response: ${detail}`);\n',
        b'    }\n',
        b'    return response.json();\n',
        b'  } catch (err) {\n',
        b'    if (err instanceof DOMException && err.name == "AbortError") {\n',
        b'      throw new Error("Chat request timed out");\n',
        b'    }\n',
        b'    throw err;\n',
        b'  } finally { clearTimeout(timeoutId); }\n',
        b'}\n',
    ]
    
    new_types = b''.join(new_types_list)
    prefix_end = content.find(b'export interface ChatResponse {')
    if prefix_end >= 0:
        prefix = content[:prefix_end + len(b'export interface ChatResponse {\n  response: string;\n}')]
    else:
        prefix = content[:idx]
    
    new_content = prefix + b'export async function fetchChat(message: string, moduleId?: string): Promise<any> {\n' + \
        b'  const controller = new AbortController();\n' + \
        b'  const timeoutId = setTimeout(() => controller.abort(), 30_000);\n' + \
        b'  const url = new URL(`${API_BASE}/api/overview/chat`);\n' + \
        b'  try {\n' + \
        b'    const response = await fetch(url.toString(), {\n' + \
        b'      method: "POST",\n' + \
        b'      headers: { "Content-Type": "application/json" },\n' + \
        b'      body: JSON.stringify({ message, module_id: moduleId }),\n' + \
        b'      cache: "no-store",\n' + \
        b'      signal: controller.signal,\n' + \
        b'    });\n' + \
        b'    if (!response.ok) {\n' + \
        b'      let detail = response.statusText;\n' + \
        b'      try { const errJson = await response.json(); if (errJson?.detail) detail = errJson.detail; } catch {}\n' + \
        b'      throw new Error(`Failed to fetch chat response: ${detail}`);\n' + \
        b'    }\n' + \
        b'    return response.json();\n' + \
        b'  } catch (err) {\n' + \
        b'    if (err instanceof DOMException && err.name == "AbortError") {\n' + \
        b'      throw new Error("Chat request timed out");\n' + \
        b'    }\n' + \
        b'    throw err;\n' + \
        b'  } finally { clearTimeout(timeoutId); }\n' + \
        b'}\n'
    new_content = prefix + new_chat
    with open(r'C:\projects\UrbanOS\frontend\src\services\api\index.ts', 'wb') as f:
        f.write(new_content)
    print('Updated successfully')
else:
    print('Could not find marker')