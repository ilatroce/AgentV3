def manage_asset(bot, ticker, mode, price, pnl_trigger=None):
    try:
        # ... (Analisi stato uguale a prima) ...
        account = bot.get_account_status()
        my_pos = next((p for p in account["open_positions"] if p["symbol"] == ticker), None)
        orders = bot.info.open_orders(bot.account_address)
        my_orders = [o for o in orders if o['coin'] == ticker]
        
        limit_orders = []
        trigger_orders = []
        for o in my_orders:
            # ... (Filtro tipo ordine uguale a prima) ...
            o_type = o.get('orderType', o.get('type', 'Limit'))
            if (isinstance(o_type, dict) and 'trigger' in o_type) or \
               (isinstance(o_type, str) and 'trigger' in o_type.lower()):
                trigger_orders.append(o)
            else:
                limit_orders.append(o)

        # --- CASO A: POSIZIONE APERTA ---
        if my_pos:
            # 1. Pulizia Entry
            if limit_orders:
                print(f"🧹 [{ticker}] In posizione. Cancello Entry.")
                for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
            
            # 2. Controllo TP (Ultra-Stabile)
            entry_px = float(my_pos['entry_price'])
            pos_size = float(my_pos['size'])
            
            # C'è un TP "Sensato"?
            valid_tp = False
            for o in trigger_orders:
                trig_px = float(o.get('triggerPx', o.get('limitPx', 0)))
                # Se il TP è sopra l'entry (per Long) o sotto (per Short), è valido.
                # Non controlliamo la size esatta, basta che esista.
                if mode == 'LONG' and trig_px > entry_px: valid_tp = True
                if mode == 'SHORT' and trig_px < entry_px: valid_tp = True
                
                if valid_tp: break # Trovato! Non toccare nulla.

            if valid_tp:
                # print(f"✅ [{ticker}] TP Valido presente.")
                return

            # Se siamo qui, NON c'è un TP valido. 
            # Cancelliamo tutto il vecchio (magari TP errati)
            if trigger_orders:
                print(f"♻️ [{ticker}] TP errati. Pulisco.")
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            # Piazza Nuovo TP
            if mode == 'LONG':
                target_px = round(entry_px + SUI_TP, 4)
                is_buy = False
                if target_px <= price: target_px = price * 1.002
            else:
                target_px = round(entry_px - SOL_TP, 2)
                is_buy = True
                if target_px >= price: target_px = price * 0.998

            print(f"🛡️ [{ticker}] Set TP @ {target_px}")
            bot.place_take_profit(ticker, is_buy, pos_size, target_px)

        # --- CASO B: FLAT (Uguale a prima) ---
        else:
            if trigger_orders: # Pulisci TP vecchi
                for o in trigger_orders: bot.exchange.cancel(ticker, o['oid'])

            should_enter = True
            if mode == 'SHORT' and (pnl_trigger is None or pnl_trigger > -0.05):
                should_enter = False
                if limit_orders: 
                    for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                return 

            if should_enter:
                if mode == 'LONG': 
                    target = round(price - SUI_OFFSET, 4)
                    is_buy = True
                else: 
                    target = round(price + SOL_OFFSET, 2)
                    is_buy = False

                amt = round(POSITION_SIZE_USD / target, 1)

                # Trailing Entry
                order_ok = False
                if limit_orders:
                    if len(limit_orders) > 1:
                        for o in limit_orders: bot.exchange.cancel(ticker, o['oid'])
                    else:
                        cur_px = float(limit_orders[0]['limitPx'])
                        if abs(cur_px - target) < (target * 0.0005): order_ok = True
                        else: bot.exchange.cancel(ticker, limit_orders[0]['oid'])
                
                if not order_ok:
                    print(f"🔫 [{ticker}] Set Entry @ {target}")
                    bot.exchange.order(ticker, is_buy, amt, target, {"limit": {"tif": "Gtc"}})
                    db_utils.log_bot_operation({"operation": "OPEN", "symbol": ticker, "direction": mode, "agent": AGENT_NAME})

    except Exception as e:
        print(f"Err {ticker}: {e}")
