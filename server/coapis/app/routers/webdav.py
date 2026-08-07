# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
CoApis WebDAV API - 提供 WebDAV 协议支持，允许用户通过 WebDAV 客户端访问工作空间文件

支持的 DAV 方法：
- PROPFIND: 获取文件或目录属性（返回 XML）
- MKCOL: 创建目录
- PUT: 上传/更新文件
- DELETE: 删除文件/目录
- COPY: 复制文件/目录
- MOVE: 移动文件/目录
"""

import os
import xml.etree.ElementTree as ET
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import Response

from ..auth import get_current_user
from ...constant import WORKSPACES_DIR

router = APIRouter(prefix="/webdav", tags=["WebDAV"])


def _get_workspace_dir(username: str) -> str:
    """获取用户工作空间目录"""
    return os.path.join(WORKSPACES_DIR, username, "files")


def _path_to_local(workspace_dir: str, webdav_path: str) -> str:
    """将 WebDAV 路径转换为本地文件系统路径"""
    # webdav_path 类似 /webdav/username/docs/file.txt
    # 移除前缀 /webdav/<username>/
    parts = webdav_path.strip("/").split("/", 2)
    if len(parts) < 3:
        return workspace_dir
    
    local_rel_path = parts[2] if len(parts) > 2 else ""
    return os.path.join(workspace_dir, local_rel_path.lstrip("/"))


def _is_directory(local_path: str) -> bool:
    """检查路径是否为目录"""
    return os.path.isdir(local_path)


def _get_file_info_xml(local_path: str, webdav_href: str, is_collection: bool = False):
    """生成 DAV PROPFIND 响应的 XML 片段"""
    propfind_response = ET.Element(
        "{DAV:}response",
        attrib={"{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": "dav_schema.xsd"}
    )
    
    href = ET.SubElement(propfind_response, "{DAV:}href")
    href.text = webdav_href
    
    propstat = ET.SubElement(propfind_response, "{DAV:}propstat")
    prop = ET.SubElement(propstat, "{DAV:}prop")
    
    resourcetype = ET.SubElement(prop, "{DAV:}resourcetype")
    if is_collection:
        collection = ET.SubElement(resourcetype, "{DAV:}collection")
    else:
        pass  # 非集合资源不添加 collection 元素
    
    getlastmodified = ET.SubElement(prop, "{DAV:}getlastmodified")
    import time
    mtime = int(os.path.getmtime(local_path)) if os.path.exists(local_path) and not is_collection else int(time.time())
    getlastmodified.text = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime))
    
    getcontentlength = ET.SubElement(prop, "{DAV:}getcontentlength")
    if not is_collection and os.path.exists(local_path):
        getcontentlength.text = str(os.path.getsize(local_path))
    else:
        getcontentlength.text = "0"
    
    getetag = ET.SubElement(prop, "{DAV:}getetag")
    getetag.text = f'"{hash(local_path)}"'
    
    displayname = ET.SubElement(prop, "{DAV:}displayname")
    displayname.text = os.path.basename(webdav_href.rstrip("/")) or "root"
    
    return propfind_response


@router.api_route("/{username:path}/{path:.*}", methods=["PROPFIND", "MKCOL", "PUT", "DELETE", "COPY", "MOVE", "OPTIONS"])
async def webdav_handler(request: Request, username: str, path: str):
    """WebDAV 主处理器"""
    
    # Get current user from auth context
    try:
        user_info = get_current_user(request)
        if user_info.get("username") != username:
            raise HTTPException(status_code=403, detail="Unauthorized")
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required")

    workspace_dir = _get_workspace_dir(username)
    local_path = _path_to_local(workspace_dir, f"/webdav/{username}/{path}")

    # Handle different DAV methods
    dav_method = request.method
    
    if dav_method == "OPTIONS":
        return Response(
            headers={
                "DAV": "1, 2, 3",
                "Allow": "PROPFIND, MKCOL, PUT, DELETE, COPY, MOVE, OPTIONS, GET, HEAD",
                "Public": "PROPFIND, MKCOL, PUT, DELETE, COPY, MOVE, OPTIONS, GET, HEAD"
            }
        )

    elif dav_method == "MKCOL":
        # Create directory
        if os.path.exists(local_path):
            raise HTTPException(status_code=405, detail="Method Not Allowed - resource already exists")
        
        try:
            os.makedirs(local_path, exist_ok=True)
            return Response(status_code=201)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create directory: {str(e)}")

    elif dav_method == "DELETE":
        # Delete file or directory
        if not os.path.exists(local_path):
            raise HTTPException(status_code=404, detail="Not Found")
        
        try:
            if _is_directory(local_path):
                import shutil
                shutil.rmtree(local_path)
            else:
                os.remove(local_path)
            return Response(status_code=204)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")

    elif dav_method == "PUT":
        # Upload/Update file
        try:
            content = await request.body()
            
            # Ensure parent directory exists
            parent_dir = os.path.dirname(local_path)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
            
            with open(local_path, 'wb') as f:
                f.write(content)
            
            return Response(status_code=201)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

    elif dav_method == "COPY":
        # Copy file/directory
        destination = request.headers.get("Destination", "")
        if not destination.startswith(f"http://{request.headers.get('Host')}/webdav/{username}/"):
            raise HTTPException(status_code=403, detail="Invalid Destination")
        
        dest_local_path = _path_to_local(workspace_dir, destination.replace(f"http://{request.headers.get('Host')}", ""))
        
        try:
            if _is_directory(local_path):
                import shutil
                if os.path.exists(dest_local_path):
                    raise HTTPException(status_code=409, detail="Destination already exists")
                shutil.copytree(local_path, dest_local_path)
            else:
                if os.path.exists(dest_local_path):
                    raise HTTPException(status_code=409, detail="Destination already exists")
                import shutil
                shutil.copy2(local_path, dest_local_path)
            
            return Response(status_code=201)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to copy: {str(e)}")

    elif dav_method == "MOVE":
        # Move file/directory
        destination = request.headers.get("Destination", "")
        if not destination.startswith(f"http://{request.headers.get('Host')}/webdav/{username}/"):
            raise HTTPException(status_code=403, detail="Invalid Destination")
        
        dest_local_path = _path_to_local(workspace_dir, destination.replace(f"http://{request.headers.get('Host')}", ""))
        
        try:
            if os.path.exists(dest_local_path):
                raise HTTPException(status_code=409, detail="Destination already exists")
            
            import shutil
            if _is_directory(local_path):
                shutil.move(local_path, dest_local_path)
            else:
                shutil.move(local_path, dest_local_path)
            
            return Response(status_code=201)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to move: {str(e)}")

    elif dav_method == "PROPFIND":
        # Return DAV properties XML
        try:
            depth = request.headers.get("Depth", "0")
            
            # Build response XML
            multistatus = ET.Element("{DAV:}multistatus")
            
            webdav_href = f"/webdav/{username}/{path or ''}"
            local_check_path = _path_to_local(workspace_dir, webdav_href) if path else workspace_dir
            
            is_collection = _is_directory(local_check_path) or not os.path.exists(local_check_path)
            
            response = _get_file_info_xml(local_check_path if os.path.exists(local_check_path) else workspace_dir, webdav_href, is_collection=is_collection)
            multistatus.append(response)

            # If depth > 0 and it's a directory, list children
            if is_collection and depth in ["1", "infinity"]:
                try:
                    for item in os.listdir(local_check_path):
                        child_local = os.path.join(local_check_path, item)
                        child_href = f"/webdav/{username}/{path}/{item}" if path else f"/webdav/{username}/{item}"
                        child_response = _get_file_info_xml(child_local, child_href, is_collection=_is_directory(child_local))
                        multistatus.append(child_response)
                except Exception:
                    pass  # Ignore listing errors

            xml_content = ET.tostring(multistatus, encoding="utf-8")
            
            return Response(
                content=xml_content,
                status_code=207,
                media_type="application/xml; charset=utf-8",
                headers={
                    "DAV": "1, 2, 3",
                    "Content-Type": "application/xml; charset=utf-8"
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process PROPFIND: {str(e)}")

    else:
        raise HTTPException(
            status_code=405, 
            detail=f"Method {dav_method} not supported for WebDAV"
        )
