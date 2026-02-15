# mcp-service/services/service_monitor.py
import requests
import time
from datetime import datetime

class ServiceMonitor:
    def __init__(self):
        self.services = {
            'excel-processor': 'http://excel-processor:5001/health',
            'admin-gateway': 'http://admin-gateway:3001/health'
        }
        self.status_history = {}

    def check_service(self, service_name):
        """检查单个服务的状态"""
        url = self.services.get(service_name)
        if not url:
            return {'status': 'unknown', 'message': 'Service not found'}
        
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                status = 'healthy'
            else:
                status = 'unhealthy'
        except Exception as e:
            status = 'down'
            message = str(e)
        
        result = {'status': status, 'timestamp': datetime.now().isoformat()}
        if 'message' in locals():
            result['message'] = message
        
        # 更新状态历史
        if service_name not in self.status_history:
            self.status_history[service_name] = []
        self.status_history[service_name].append(result)
        
        return result

    def check_all_services(self):
        """检查所有服务的状态"""
        results = {}
        for service_name in self.services:
            results[service_name] = self.check_service(service_name)
        return results