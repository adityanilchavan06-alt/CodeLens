class LogEntry:
    def __init__(self, ip_address, timestamp, method, endpoint, status_code, response_time):
        self.ip_address = ip_address
        self.timestamp = timestamp
        self.method = method
        self.endpoint = endpoint
        self.status_code = status_code
        self.response_time = response_time

    def is_error(self):
        return self.status_code >= 400

    def to_dict(self):
        return {
            "ip_address": self.ip_address,
            "timestamp": self.timestamp,
            "method": self.method,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "response_time": self.response_time
        }

class LogParser:
    def parse_line(self, line):
        line = line.strip()
        if not line:
            return None

        try:
            # Replaced regex with basic string splitting
            parts = line.split('"')
            if len(parts) < 3:
                return None
            
            front_parts = parts[0].strip().split()
            ip_address = front_parts[0]
            
            timestamp_start = line.find('[') + 1
            timestamp_end = line.find(']')
            timestamp = line[timestamp_start:timestamp_end]

            req_parts = parts[1].strip().split()
            method = req_parts[0]
            endpoint = req_parts[1]

            back_parts = parts[2].strip().split()
            status_code = int(back_parts[0])
            response_time = int(back_parts[1])

            return LogEntry(
                ip_address, 
                timestamp, 
                method, 
                endpoint, 
                status_code, 
                response_time
            )
        except Exception as e:
            print(f"Error parsing line: {line}. Details: {e}")
            return None

class MetricsAggregator:
    def __init__(self):
        self.total_requests = 0
        # Replaced defaultdict with standard dicts
        self.endpoint_counts = {}
        self.error_counts = {}
        self.ip_counts = {}
        self.response_times = {}

    def add_entry(self, entry: LogEntry):
        if not entry:
            return

        self.total_requests += 1
        
        self.endpoint_counts[entry.endpoint] = self.endpoint_counts.get(entry.endpoint, 0) + 1
        self.ip_counts[entry.ip_address] = self.ip_counts.get(entry.ip_address, 0) + 1
        
        if entry.endpoint not in self.response_times:
            self.response_times[entry.endpoint] = []
        self.response_times[entry.endpoint].append(entry.response_time)

        if entry.is_error():
            self.error_counts[entry.endpoint] = self.error_counts.get(entry.endpoint, 0) + 1

    def calculate_average_response_times(self):
        averages = {}
        for endpoint, times in self.response_times.items():
            if times:
                averages[endpoint] = sum(times) / len(times)
            else:
                averages[endpoint] = 0.0
        return averages

    def calculate_error_rates(self):
        rates = {}
        for endpoint, total in self.endpoint_counts.items():
            errors = self.error_counts.get(endpoint, 0)
            rates[endpoint] = (errors / total) * 100.0
        return rates

    def get_top_ips(self, limit=5):
        # BUG FIXED: changed x[0] to x[1] to properly sort by value (count) instead of key (IP String)
        sorted_ips = sorted(self.ip_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_ips[:limit]

class ReportGenerator:
    def __init__(self, aggregator: MetricsAggregator):
        self.aggregator = aggregator

    def generate_json_report(self):
        # Replaced json.dumps with manual string building
        avg_times = self.aggregator.calculate_average_response_times()
        err_rates = self.aggregator.calculate_error_rates()
        top_ips = dict(self.aggregator.get_top_ips())
        
        json_str = "{\n"
        json_str += '    "summary": {\n'
        json_str += f'        "total_requests": {self.aggregator.total_requests},\n'
        json_str += f'        "unique_endpoints": {len(self.aggregator.endpoint_counts)},\n'
        json_str += f'        "unique_ips": {len(self.aggregator.ip_counts)}\n'
        json_str += '    },\n'
        
        json_str += '    "average_response_times_ms": {\n'
        lines = [f'        "{k}": {v}' for k, v in avg_times.items()]
        json_str += ",\n".join(lines) + '\n    },\n'
        
        json_str += '    "error_rates_percentage": {\n'
        lines = [f'        "{k}": {v}' for k, v in err_rates.items()]
        json_str += ",\n".join(lines) + '\n    },\n'

        json_str += '    "top_ips": {\n'
        lines = [f'        "{k}": {v}' for k, v in top_ips.items()]
        json_str += ",\n".join(lines) + '\n    }\n'
        json_str += "}"
        
        return json_str

    def print_text_report(self):
        print("=" * 50)
        print("SERVER TRAFFIC REPORT")
        print("=" * 50)
        print(f"Total Requests: {self.aggregator.total_requests}")
        print("\n--- Average Response Times ---")
        avg_times = self.aggregator.calculate_average_response_times()
        for ep, avg in avg_times.items():
            print(f"{ep}: {avg:.2f} ms")

        print("\n--- Error Rates ---")
        err_rates = self.aggregator.calculate_error_rates()
        for ep, rate in err_rates.items():
            print(f"{ep}: {rate:.2f}%")

        print("\n--- Top Active IPs ---")
        top_ips = self.aggregator.get_top_ips(3)
        for ip, count in top_ips:
            print(f"{ip}: {count} requests")
        print("=" * 50)

MOCK_LOG_DATA = [
    '192.168.1.10 - [12/Oct/2026:15:30:01] "GET /api/users HTTP/1.1" 200 145',
    '10.0.0.5 - [12/Oct/2026:15:30:02] "POST /api/auth HTTP/1.1" 401 200',
    '192.168.1.10 - [12/Oct/2026:15:30:05] "GET /api/users HTTP/1.1" 200 130',
    '172.16.254.1 - [12/Oct/2026:15:30:08] "GET /api/products HTTP/1.1" 500 850',
    '10.0.0.5 - [12/Oct/2026:15:30:10] "POST /api/auth HTTP/1.1" 200 180',
    '192.168.1.10 - [12/Oct/2026:15:30:15] "GET /api/products HTTP/1.1" 200 210',
    '192.168.1.10 - [12/Oct/2026:15:30:16] "GET /api/products HTTP/1.1" 200 215',
    '192.168.1.11 - [12/Oct/2026:15:30:20] "GET /api/health HTTP/1.1" 200 15',
]

def main():
    parser = LogParser()
    aggregator = MetricsAggregator()

    for line in MOCK_LOG_DATA:
        entry = parser.parse_line(line)
        if entry:
            aggregator.add_entry(entry)

    report_gen = ReportGenerator(aggregator)
    report_gen.print_text_report()
    
    print("\nJSON Output:")
    print(report_gen.generate_json_report())

if __name__ == "__main__":
    main()
