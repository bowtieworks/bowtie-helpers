#!/usr/bin/env python3
"""
Unified Bowtie Traffic Analyzer
Combines device/user mapping fetch with traffic analysis in one tool
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import argparse
import json
import os
import sys
import getpass
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich import box
from rich.text import Text

console = Console()

def get_traffic_color(bytes_value: float) -> str:
    """Get color based on traffic amount."""
    if bytes_value == 0:
        return "dim white"
    elif bytes_value < 1024 * 1024:  # < 1 MB
        return "cyan"
    elif bytes_value < 100 * 1024 * 1024:  # < 100 MB
        return "green"
    elif bytes_value < 500 * 1024 * 1024:  # < 500 MB
        return "yellow"
    elif bytes_value < 1024 * 1024 * 1024:  # < 1 GB
        return "bright_yellow"
    else:  # >= 1 GB
        return "bright_red"

class BowtieTrafficAnalyzer:
    def __init__(self, prometheus_url="http://localhost:9090", mappings_dir="./mappings"):
        self.prometheus_url = prometheus_url
        self.mappings_dir = Path(mappings_dir)
        self.mappings_dir.mkdir(exist_ok=True)
        self.device_mappings = {}
        self.user_mappings = {}
        self.session = requests.Session()
        
    def check_mappings_age(self) -> Optional[float]:
        """Check how old the mapping files are (in hours)."""
        devices_file = self.mappings_dir / "devices.json"
        if devices_file.exists():
            age_seconds = datetime.now().timestamp() - devices_file.stat().st_mtime
            return age_seconds / 3600
        return None
    
    def fetch_mappings(self, controller_url: str, cookie: str) -> bool:
        """Fetch device and user mappings from controller."""
        console.print(f"\n📡 Fetching mappings from {controller_url}...", style="cyan")
        
        controller_url = controller_url.rstrip('/')
        headers = {'Cookie': cookie}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            
            task = progress.add_task("Testing connection...", total=None)
            
            try:
                # Fetch devices
                response = self.session.get(
                    f"{controller_url}/-net/api/v0/device",
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code != 200:
                    console.print(f"❌ Failed (HTTP {response.status_code})", style="red")
                    console.print(f"  Error: {response.text[:200]}", style="red")
                    return False
                
                progress.update(task, description="Fetching devices...")
                
                devices_data = response.json()
                devices_file = self.mappings_dir / "devices.json"
                with open(devices_file, 'w') as f:
                    json.dump(devices_data, f, indent=2)
                
                device_count = len(devices_data.get('devices', {}))
                
                # Fetch users
                progress.update(task, description="Fetching users...")
                response = self.session.get(
                    f"{controller_url}/-net/api/v0/users",
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code != 200:
                    console.print(f"❌ Failed (HTTP {response.status_code})", style="red")
                    return False
                
                users_data = response.json()
                users_file = self.mappings_dir / "users.json"
                with open(users_file, 'w') as f:
                    json.dump(users_data, f, indent=2)
                
                user_count = len(users_data)
                
            except requests.exceptions.Timeout:
                console.print("❌ Connection timeout", style="red")
                return False
            except requests.exceptions.ConnectionError as e:
                console.print(f"❌ Connection error: {e}", style="red")
                return False
            except Exception as e:
                console.print(f"❌ Error: {e}", style="red")
                return False
        
        console.print(f"✅ Fetched [bold]{device_count}[/bold] devices and [bold]{user_count}[/bold] users", style="green")
        return True
    
    def prompt_for_mappings_update(self, force=False) -> bool:
        """Prompt user to update mappings if needed."""
        age = self.check_mappings_age()
        
        update_needed = force or age is None
        update_recommended = age and age > 24
        
        if not update_needed and not update_recommended:
            console.print(f"\n📊 Mappings are {age:.1f} hours old", style="green")
            if not Confirm.ask("Update mappings anyway?", default=False):
                return True
        
        if age is None:
            console.print("\n⚠️  No device/user mappings found. Fetching is required.", style="yellow")
        elif update_recommended:
            console.print(f"\n⚠️  Mappings are {age:.1f} hours old. Update recommended.", style="yellow")
        
        console.rule("FETCH DEVICE/USER MAPPINGS", style="blue")
        
        panel_content = """To fetch mappings, you'll need:
1. Your controller URL
2. A valid session cookie from the controller

[cyan]Cookie instructions:[/cyan]
  1. Log into your Bowtie Controller web UI
  2. Open DevTools (F12) → Application → Cookies
  3. Copy the session cookie (e.g., grafana_session=...)"""
        
        console.print(Panel(panel_content, border_style="cyan"))
        
        if not Confirm.ask("Fetch mappings now?", default=True):
            if age is None:
                console.print("❌ Cannot proceed without mappings", style="red")
                return False
            else:
                console.print("⚠️  Using existing mappings", style="yellow")
                return True
        
        controller_url = Prompt.ask("\nController URL (e.g., https://controller-1.bowtie.security)")
        if not controller_url:
            console.print("❌ Controller URL required", style="red")
            return False
        
        console.print("\nPaste cookie value (hidden):", style="cyan")
        cookie = getpass.getpass("Cookie: ").strip()
        if not cookie:
            console.print("❌ Cookie required", style="red")
            return False
        
        if self.fetch_mappings(controller_url, cookie):
            console.print("✅ Mappings updated successfully!", style="green")
            return True
        else:
            console.print("\n❌ Failed to fetch mappings", style="red")
            
            troubleshooting = """[yellow]Troubleshooting:[/yellow]
  1. Ensure cookie hasn't expired (try logging in again)
  2. Verify the URL matches exactly what you use in browser
  3. Check cookie format (should be: name=value)
  
[cyan]Test manually with:[/cyan]
  curl -H "Cookie: YOUR_COOKIE" "{url}/-net/api/v0/device" """.format(url=controller_url)
            
            console.print(Panel(troubleshooting))
            
            if age is not None:
                return Confirm.ask("Use existing mappings anyway?", default=False)
            return False
    
    def load_mappings(self) -> bool:
        """Load device and user mappings from JSON files."""
        devices_file = self.mappings_dir / "devices.json"
        users_file = self.mappings_dir / "users.json"
        
        if not devices_file.exists():
            return False
        
        with open(devices_file, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'devices' in data:
                devices = data['devices']
            else:
                devices = data
            
            if isinstance(devices, dict):
                devices = devices.values()
            
            for device in devices:
                public_key = device.get('public_key')
                if public_key:
                    self.device_mappings[public_key] = {
                        'name': device.get('name', 'Unknown'),
                        'user_id': device.get('assigned_to_user') or 
                                  device.get('last_successful_assigned_to_user', 'Unknown')
                    }
        
        if users_file.exists():
            with open(users_file, 'r') as f:
                users = json.load(f)
                for user_id, user_data in users.items():
                    if isinstance(user_data, dict):
                        self.user_mappings[user_id] = user_data.get('email', user_id)
                    else:
                        self.user_mappings[user_id] = user_id
        
        console.print(f"📂 Loaded [bold]{len(self.device_mappings)}[/bold] devices, "
                     f"[bold]{len(self.user_mappings)}[/bold] users", style="cyan")
        return True
    
    def query(self, query: str) -> Dict:
        """Execute Prometheus query."""
        try:
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={'query': query}
            )
            if response.status_code == 200:
                return response.json()
            return {'data': {'result': []}}
        except:
            return {'data': {'result': []}}
    
    def enrich_device_info(self, public_key: str) -> Tuple[str, str]:
        """Get device name and user email for a public key."""
        device_info = self.device_mappings.get(public_key, {})
        device_name = device_info.get('name', public_key[:20] + '...')
        user_id = device_info.get('user_id', 'Unknown')
        user_email = self.user_mappings.get(user_id, user_id)
        return device_name, user_email
    
    def get_traffic_detailed(self, time_range="1h") -> pd.DataFrame:
        """Get detailed traffic with sent/received separated."""
        sent_query = f'''
        sum by (public_key, appliance_id, interface) (
            increase(wireguard_sent_bytes_total[{time_range}])
        )
        '''
        
        received_query = f'''
        sum by (public_key, appliance_id, interface) (
            increase(wireguard_received_bytes_total[{time_range}])
        )
        '''
        
        sent_result = self.query(sent_query)
        received_result = self.query(received_query)
        
        traffic_data = {}
        
        # Process sent bytes
        if sent_result and 'data' in sent_result and 'result' in sent_result['data']:
            for metric in sent_result['data']['result']:
                m = metric['metric']
                public_key = m.get('public_key', 'unknown')
                controller = m.get('appliance_id', 'unknown')
                sent_bytes = float(metric['value'][1])
                
                key = (public_key, controller)
                if key not in traffic_data:
                    traffic_data[key] = {'sent': 0, 'received': 0}
                traffic_data[key]['sent'] = sent_bytes
        
        # Process received bytes
        if received_result and 'data' in received_result and 'result' in received_result['data']:
            for metric in received_result['data']['result']:
                m = metric['metric']
                public_key = m.get('public_key', 'unknown')
                controller = m.get('appliance_id', 'unknown')
                received_bytes = float(metric['value'][1])
                
                key = (public_key, controller)
                if key not in traffic_data:
                    traffic_data[key] = {'sent': 0, 'received': 0}
                traffic_data[key]['received'] = received_bytes
        
        data = []
        for (public_key, controller), metrics in traffic_data.items():
            device_name, user_email = self.enrich_device_info(public_key)
            total_bytes = metrics['sent'] + metrics['received']
            
            data.append({
                'public_key': public_key,
                'device_name': device_name,
                'user_email': user_email,
                'controller': controller,
                'sent_bytes': metrics['sent'],
                'received_bytes': metrics['received'],
                'total_bytes': total_bytes,
                'sent_human': self.format_bytes(metrics['sent']),
                'received_human': self.format_bytes(metrics['received']),
                'total_human': self.format_bytes(total_bytes)
            })
        
        return pd.DataFrame(data).sort_values('total_bytes', ascending=False) if data else pd.DataFrame()
    
    def get_aggregated_traffic(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate traffic across all controllers by device."""
        if df.empty:
            return pd.DataFrame()
        
        agg_df = df.groupby('public_key').agg({
            'device_name': 'first',
            'user_email': 'first',
            'sent_bytes': 'sum',
            'received_bytes': 'sum',
            'total_bytes': 'sum'
        }).reset_index()
        
        agg_df['sent_human'] = agg_df['sent_bytes'].apply(self.format_bytes)
        agg_df['received_human'] = agg_df['received_bytes'].apply(self.format_bytes)
        agg_df['total_human'] = agg_df['total_bytes'].apply(self.format_bytes)
        
        return agg_df.sort_values('total_bytes', ascending=False)
    
    def get_user_traffic(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate traffic by user across all devices and controllers."""
        if df.empty:
            return pd.DataFrame()
        
        user_df = df.groupby('user_email').agg({
            'sent_bytes': 'sum',
            'received_bytes': 'sum',
            'total_bytes': 'sum'
        }).reset_index()
        
        device_counts = df.groupby('user_email')['device_name'].nunique().reset_index()
        device_counts.columns = ['user_email', 'device_count']
        
        user_df = user_df.merge(device_counts, on='user_email')
        
        user_df['sent_human'] = user_df['sent_bytes'].apply(self.format_bytes)
        user_df['received_human'] = user_df['received_bytes'].apply(self.format_bytes)
        user_df['total_human'] = user_df['total_bytes'].apply(self.format_bytes)
        
        return user_df.sort_values('total_bytes', ascending=False)
    
    def get_summary(self, time_range="24h") -> Dict:
        """Get summary statistics."""
        total_query = f'''
        sum(
            increase(wireguard_sent_bytes_total[{time_range}]) + 
            increase(wireguard_received_bytes_total[{time_range}])
        )
        '''
        total_result = self.query(total_query)
        total_traffic = 0
        if total_result and 'data' in total_result and 'result' in total_result['data'] and total_result['data']['result']:
            total_traffic = float(total_result['data']['result'][0]['value'][1])
        
        sent_query = f'sum(increase(wireguard_sent_bytes_total[{time_range}]))'
        received_query = f'sum(increase(wireguard_received_bytes_total[{time_range}]))'
        
        sent_result = self.query(sent_query)
        received_result = self.query(received_query)
        
        sent_total = 0
        if sent_result and 'data' in sent_result and 'result' in sent_result['data'] and sent_result['data']['result']:
            sent_total = float(sent_result['data']['result'][0]['value'][1])
        
        received_total = 0
        if received_result and 'data' in received_result and 'result' in received_result['data'] and received_result['data']['result']:
            received_total = float(received_result['data']['result'][0]['value'][1])
        
        active_query = f'''
        count(
            sum by (public_key) (
                increase(wireguard_sent_bytes_total[{time_range}]) + 
                increase(wireguard_received_bytes_total[{time_range}])
            ) > 0
        )
        '''
        active_result = self.query(active_query)
        active_devices = 0
        if active_result and 'data' in active_result and 'result' in active_result['data'] and active_result['data']['result']:
            active_devices = int(float(active_result['data']['result'][0]['value'][1]))
        
        controllers_query = 'count by (appliance_id) (up)'
        controllers_result = self.query(controllers_query)
        controllers = {}
        if controllers_result and 'data' in controllers_result and 'result' in controllers_result['data']:
            controllers = {m['metric'].get('appliance_id', 'unknown'): 'UP' for m in controllers_result['data']['result']}
        
        return {
            'total_traffic': self.format_bytes(total_traffic),
            'sent_total': self.format_bytes(sent_total),
            'received_total': self.format_bytes(received_total),
            'active_devices': active_devices,
            'controllers': controllers,
            'time_range': time_range
        }
    
    def format_bytes(self, bytes_value: float) -> str:
        """Format bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"

def create_traffic_table(df: pd.DataFrame, title: str = "", show_controller: bool = True) -> Table:
    """Create a rich table for traffic data."""
    if show_controller and 'controller' in df.columns:
        table = Table(title=title, box=box.SIMPLE_HEAD, show_footer=True)
        table.add_column("Device", style="white", no_wrap=True)
        table.add_column("User", style="white")
        table.add_column("Controller", style="cyan")
        table.add_column("Sent", justify="right")
        table.add_column("Received", justify="right")
        table.add_column("Total", justify="right", footer="TOTALS", footer_style="bold white")
    else:
        table = Table(title=title, box=box.SIMPLE_HEAD, show_footer=True)
        table.add_column("Device", style="white", no_wrap=True)
        table.add_column("User", style="white")
        table.add_column("Sent", justify="right")
        table.add_column("Received", justify="right")
        table.add_column("Total", justify="right", footer="TOTALS", footer_style="bold white")
    
    analyzer = BowtieTrafficAnalyzer()
    
    total_sent = 0
    total_received = 0
    total_all = 0
    
    for _, row in df.iterrows():
        sent_color = get_traffic_color(row['sent_bytes'])
        received_color = get_traffic_color(row['received_bytes'])
        total_color = get_traffic_color(row['total_bytes'])
        
        total_sent += row['sent_bytes']
        total_received += row['received_bytes']
        total_all += row['total_bytes']
        
        # Handle None values safely
        device_name = str(row['device_name'] or 'Unknown')[:25]
        user_email = str(row['user_email'] or 'Unknown')[:30]
        controller = str(row['controller'] or 'Unknown')[:12] if 'controller' in row else None
        
        if show_controller and 'controller' in df.columns:
            table.add_row(
                device_name,
                Text(user_email, style=get_traffic_color(row['total_bytes'])),
                controller,
                Text(analyzer.format_bytes(row['sent_bytes']), style=sent_color),
                Text(analyzer.format_bytes(row['received_bytes']), style=received_color),
                Text(analyzer.format_bytes(row['total_bytes']), style=total_color)
            )
        else:
            table.add_row(
                device_name,
                Text(user_email, style=get_traffic_color(row['total_bytes'])),
                Text(analyzer.format_bytes(row['sent_bytes']), style=sent_color),
                Text(analyzer.format_bytes(row['received_bytes']), style=received_color),
                Text(analyzer.format_bytes(row['total_bytes']), style=total_color)
            )
    
    # Add footer totals
    if show_controller and 'controller' in df.columns:
        table.columns[3].footer = Text(analyzer.format_bytes(total_sent), style=get_traffic_color(total_sent))
        table.columns[4].footer = Text(analyzer.format_bytes(total_received), style=get_traffic_color(total_received))
        table.columns[5].footer = Text(analyzer.format_bytes(total_all), style=get_traffic_color(total_all))
    else:
        table.columns[2].footer = Text(analyzer.format_bytes(total_sent), style=get_traffic_color(total_sent))
        table.columns[3].footer = Text(analyzer.format_bytes(total_received), style=get_traffic_color(total_received))
        table.columns[4].footer = Text(analyzer.format_bytes(total_all), style=get_traffic_color(total_all))
    
    return table

def main():
    parser = argparse.ArgumentParser(
        description='Unified Bowtie Traffic Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate report (will prompt for mappings update if needed)
  %(prog)s --time-range 24h
  
  # Force update mappings before analysis
  %(prog)s --time-range 24h --update-mappings
  
  # Skip mappings update prompt
  %(prog)s --time-range 1h --skip-update
  
  # Generate CSV reports
  %(prog)s --time-range 24h --output-prefix daily_report
  
  # Show only user summary
  %(prog)s --time-range 7d --users-only
        """
    )
    parser.add_argument('--time-range', default='24h', 
                       help='Time range (1h, 6h, 24h, 7d, 30d)')
    parser.add_argument('--output-prefix', 
                       help='Prefix for output CSV files')
    parser.add_argument('--prometheus', default='http://localhost:9090', 
                       help='Prometheus URL')
    parser.add_argument('--mappings-dir', default='./mappings',
                       help='Directory for device/user mappings')
    parser.add_argument('--users-only', action='store_true',
                       help='Show only user summary')
    parser.add_argument('--update-mappings', action='store_true',
                       help='Force update device/user mappings')
    parser.add_argument('--skip-update', action='store_true',
                       help='Skip mappings update prompt')
    
    args = parser.parse_args()
    
    analyzer = BowtieTrafficAnalyzer(args.prometheus, args.mappings_dir)
    
    if not args.skip_update:
        if not analyzer.prompt_for_mappings_update(force=args.update_mappings):
            console.print("\n❌ Cannot proceed without valid mappings", style="red bold")
            sys.exit(1)
    
    if not analyzer.load_mappings():
        console.print("\n❌ Failed to load mappings", style="red bold")
        console.print(f"Please ensure mapping files exist in: {args.mappings_dir}")
        sys.exit(1)
    
    try:
        # Get summary
        console.rule("BOWTIE TRAFFIC SUMMARY", style="blue")
        summary = analyzer.get_summary(args.time_range)
        
        summary_table = Table(box=box.SIMPLE, show_header=False)
        summary_table.add_column("Label", style="cyan")
        summary_table.add_column("Value", style="white")
        
        summary_table.add_row("Time Range:", summary['time_range'])
        summary_table.add_row("Total Traffic:", summary['total_traffic'])
        summary_table.add_row("  - Sent:", summary['sent_total'])
        summary_table.add_row("  - Received:", summary['received_total'])
        summary_table.add_row("Active Devices:", str(summary['active_devices']))
        summary_table.add_row("Controllers:", str(summary['controllers']))
        
        console.print(summary_table)
        
        # Get detailed traffic
        df = analyzer.get_traffic_detailed(args.time_range)
        
        if not df.empty:
            if not args.users_only:
                # Show per-controller breakdown
                console.rule(f"TRAFFIC BY CONTROLLER (last {args.time_range})", style="blue")
                
                for controller in df['controller'].unique():
                    controller_df = df[df['controller'] == controller]
                    table = create_traffic_table(controller_df, title=f"{controller.upper()}", show_controller=False)
                    console.print(table)
                
                # Show aggregated total
                console.rule(f"TOTAL TRAFFIC - ALL CONTROLLERS COMBINED (last {args.time_range})", style="blue")
                agg_df = analyzer.get_aggregated_traffic(df)
                table = create_traffic_table(agg_df, show_controller=False)
                console.print(table)
            
            # Show user summary
            console.rule(f"TRAFFIC BY USER (last {args.time_range})", style="blue")
            
            user_df = analyzer.get_user_traffic(df)
            if not user_df.empty:
                user_table = Table(box=box.SIMPLE_HEAD, show_footer=True)
                user_table.add_column("User", style="white", footer="TOTAL", footer_style="bold white")
                user_table.add_column("Devices", justify="center", footer=str(user_df['device_count'].sum()))
                user_table.add_column("Sent", justify="right", footer=analyzer.format_bytes(user_df['sent_bytes'].sum()))
                user_table.add_column("Received", justify="right", footer=analyzer.format_bytes(user_df['received_bytes'].sum()))
                user_table.add_column("Total", justify="right", footer=analyzer.format_bytes(user_df['total_bytes'].sum()))
                
                for _, row in user_df.iterrows():
                    color = get_traffic_color(row['total_bytes'])
                    user_table.add_row(
                        Text(row['user_email'], style=color),
                        str(row['device_count']),
                        Text(row['sent_human'], style=get_traffic_color(row['sent_bytes'])),
                        Text(row['received_human'], style=get_traffic_color(row['received_bytes'])),
                        Text(row['total_human'], style=color)
                    )
                
                console.print(user_table)
            
            # Save to CSV if requested
            if args.output_prefix:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                with console.status("[bold green]Saving CSV files..."):
                    # Prepare DataFrames with human-readable values only
                    detailed_file = f"{args.output_prefix}_detailed_{timestamp}.csv"
                    df_export = df.drop(columns=['sent_bytes', 'received_bytes', 'total_bytes'], errors='ignore')
                    df_export = df_export.rename(columns={'sent_human': 'sent_bytes', 'received_human': 'received_bytes', 'total_human': 'total_bytes'})
                    df_export.to_csv(detailed_file, index=False)
                    
                    agg_file = f"{args.output_prefix}_aggregated_{timestamp}.csv"
                    agg_df = analyzer.get_aggregated_traffic(df)
                    agg_export = agg_df.drop(columns=['sent_bytes', 'received_bytes', 'total_bytes'], errors='ignore')
                    agg_export = agg_export.rename(columns={'sent_human': 'sent_bytes', 'received_human': 'received_bytes', 'total_human': 'total_bytes'})
                    agg_export.to_csv(agg_file, index=False)
                    
                    user_file = f"{args.output_prefix}_users_{timestamp}.csv"
                    user_export = user_df.drop(columns=['sent_bytes', 'received_bytes', 'total_bytes'], errors='ignore')
                    user_export = user_export.rename(columns={'sent_human': 'sent_bytes', 'received_human': 'received_bytes', 'total_human': 'total_bytes'})
                    user_export.to_csv(user_file, index=False)
                
                console.print(f"\n✅ Saved detailed traffic to [cyan]{detailed_file}[/cyan]")
                console.print(f"✅ Saved aggregated traffic to [cyan]{agg_file}[/cyan]")
                console.print(f"✅ Saved user summary to [cyan]{user_file}[/cyan]")
        else:
            console.print("\nNo traffic data found", style="yellow")
            
    except Exception as e:
        console.print(f"\n❌ Error: {e}", style="red bold")
        
        troubleshooting = """[yellow]Troubleshooting:[/yellow]
1. Check if Prometheus is running: curl http://localhost:9090
2. Check if metrics are being scraped: curl 'http://localhost:9090/api/v1/targets'
3. Ensure device/user mappings are valid in: {dir}""".format(dir=args.mappings_dir)
        
        console.print(Panel(troubleshooting))
        sys.exit(1)

if __name__ == "__main__":
    main()