# mcp-service/services/config_manager.py
import os
import json
from datetime import datetime

class ConfigManager:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = self.load_config()

    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return self.get_default_config()
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.get_default_config()

    def get_default_config(self):
        """获取默认配置"""
        return {
            'services': {
                'excel-processor': {
                    'enabled': True,
                    'port': 5001,
                    'max_file_size': 50  # MB
                },
                'admin-gateway': {
                    'enabled': True,
                    'port': 3001,
                    'ragflow_base_url': 'http://your-ragflow:80'
                }
            },
            'mcp': {
                'port': 5000,
                'check_interval': 10  # seconds
            },
            'updated_at': datetime.now().isoformat()
        }

    def save_config(self):
        """保存配置文件"""
        try:
            self.config['updated_at'] = datetime.now().isoformat()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def get_config(self, service_name=None):
        """获取配置"""
        if service_name:
            return self.config.get('services', {}).get(service_name, {})
        return self.config

    def update_config(self, service_name, new_config):
        """更新配置"""
        if service_name not in self.config.get('services', {}):
            self.config['services'][service_name] = {}
        
        self.config['services'][service_name].update(new_config)
        return self.save_config()