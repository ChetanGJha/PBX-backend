#!/usr/bin/env python3
"""
PBX Gateway & Trunk Synchronization Utility for FreeSWITCH
Syncs active Sofia Gateways & SIP Trunks from PostgreSQL into FreeSWITCH XML profiles.
"""
import sys
import os
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services.gateway_sync import sync_gateways_to_freeswitch, execute_esl_command

async def main():
    print("=" * 65)
    print("  PBX FreeSWITCH Gateway & Trunk Sync Utility")
    print("=" * 65)
    print("Synchronizing active gateways and SIP trunks from PostgreSQL...")
    try:
        res = await sync_gateways_to_freeswitch()
        print(f"\n[+] Sync Status: {'SUCCESS' if res.get('success') else 'FAILED'}")
        print(f"[+] Total Active Trunks/Gateways in DB: {res.get('total_active_gateways')}")
        print(f"[+] XML Files Written: {res.get('written_files')}")
        print(f"[+] Stale XML Files Removed: {res.get('deleted_files')}")
        print(f"[+] External Profile Gateways (ITS): {res.get('external_gateways')}")
        print(f"[+] CrossConnect Profile Gateways (Fixed Line): {res.get('crossconnect_gateways')}")
        
        print("\n" + "=" * 65)
        print("  Current FreeSWITCH Sofia Status")
        print("=" * 65)
        status_out = execute_esl_command("sofia status")
        print(status_out or "Unable to connect to FreeSWITCH ESL")
    except Exception as e:
        print(f"[-] Error syncing gateways: {e}")

if __name__ == "__main__":
    asyncio.run(main())
