#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据加载器模块
负责加载和处理导师数据
"""

import json
import os
import logging

class DataLoader:
    """数据加载器类"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def load_teacher_data(self, json_file):
        """
        加载导师数据

        数据格式：{"email": "name"}

        Args:
            json_file (str): JSON文件路径

        Returns:
            dict: 导师数据字典 {email: name}
        """
        try:
            if not os.path.exists(json_file):
                self.logger.error(f"数据文件不存在: {json_file}")
                print(f"❌ 数据文件不存在: {json_file}")
                return {}

            with open(json_file, 'r', encoding='utf-8') as f:
                teacher_data = json.load(f)

            self.logger.info(f"成功加载 {len(teacher_data)} 位导师的信息")

            return teacher_data

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON格式错误: {e}")
            print(f"❌ JSON格式错误: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"加载导师数据失败: {e}")
            print(f"❌ 加载导师数据失败: {e}")
            return {}