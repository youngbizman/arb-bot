# 2. Iterate and Match (Protecting the API rate limit)
        for game_key, x_data in fiat_games.items():
            home_nick, away_nick = clean(x_data["home"]), clean(x_data["away"])
            fiat_time = x_data["commence_time"]
            
            target_event = None
            for e in raw_poly_events:
                title = str(e.get('title', '')).lower()
                if home_nick in title and away_nick in title:
                    p_start = e.get("gameStartTime") or e.get("eventStartTime")
                    p_end = e.get("endDate")
                    if is_target_single_game(fiat_time, p_start, p_end):
                        target_event = e
                        break
                        
            if not target_event: continue
            
            # --- ALWAYS PRINT THE MATCHED GAME HEADER ---
            logger.info(f"\n🏀 MATCHED: {x_data['home']} vs {x_data['away']} | Date: {fiat_time[:10]}")
            logger.info("-" * 80)
            
            game_output = []
            
            for m in target_event.get('markets', []):
                if not m.get('acceptingOrders'): continue
                m_type = str(m.get('sportsMarketType', '')).lower()
                
                try:
                    outcomes_val, tokens_val = m.get('outcomes'), m.get('clobTokenIds')
                    if not outcomes_val or not tokens_val: continue
                    raw_outcomes = json.loads(outcomes_val) if isinstance(outcomes_val, str) else outcomes_val
                    raw_tokens = json.loads(tokens_val) if isinstance(tokens_val, str) else tokens_val
                except (json.JSONDecodeError, TypeError): continue

                if not isinstance(raw_outcomes, list) or not isinstance(raw_tokens, list): continue
                if len(raw_outcomes) != len(raw_tokens) or len(raw_outcomes) == 0: continue

                # Attribute 1 & 4: Moneylines
                if m_type in ['moneyline', 'first_half_moneyline']:
                    fiat_target = "moneyline" if m_type == 'moneyline' else "1h_moneyline"
                    display = "Moneyline" if m_type == 'moneyline' else "1H Moneyline"
                    for idx, t_name in enumerate(raw_outcomes):
                        p_nick = clean(t_name)
                        fiat_odds = x_data[fiat_target].get(p_nick)
                        if fiat_odds:
                            # ONLY FETCH CLOB IF THERE IS A FIAT MATCH
                            poly_ask = clients.get_clob_best_ask(raw_tokens[idx])
                            if poly_ask:
                                game_output.append(f"   [{display}] {t_name:<15} | Pin: {float(fiat_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                                opp_nick = home_nick if p_nick == away_nick else away_nick
                                fiat_opp_odds = x_data[fiat_target].get(opp_nick)
                                if fiat_opp_odds:
                                    arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                    if arb_sum < 1:
                                        opportunities.append(_build_opp(x_data, fiat_opp_odds, poly_ask, arb_sum, display, t_name, opp_nick))

                # Extract line for Totals/Spreads
                raw_line = m.get("line")
                if raw_line is None: continue
                try: poly_line = round(float(raw_line), 1)
                except ValueError: continue

                # Attribute 2: Totals
                if m_type in ['total', 'totals'] and poly_line in x_data["totals"]:
                    norm = [str(o).lower().strip() for o in raw_outcomes]
                    if "over" in norm and "under" in norm:
                        o_idx, u_idx = norm.index("over"), norm.index("under")
                        xb_under, xb_over = x_data["totals"][poly_line].get('under'), x_data["totals"][poly_line].get('over')
                        
                        if xb_under:
                            p_over_ask = clients.get_clob_best_ask(raw_tokens[o_idx])
                            if p_over_ask:
                                game_output.append(f"   [Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                                arb_sum = p_over_ask + (Decimal("1") / xb_under)
                                if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_under, p_over_ask, arb_sum, f"Total {poly_line}", "OVER", "UNDER"))
                        
                        if xb_over:
                            p_under_ask = clients.get_clob_best_ask(raw_tokens[u_idx])
                            if p_under_ask:
                                game_output.append(f"   [Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                                arb_sum = p_under_ask + (Decimal("1") / xb_over)
                                if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_over, p_under_ask, arb_sum, f"Total {poly_line}", "UNDER", "OVER"))

                # Attribute 3: Spreads
                elif m_type in ['spread', 'spreads']:
                    inv_fiat = -poly_line 
                    if inv_fiat in x_data["spreads"]:
                        for idx, t_name in enumerate(raw_outcomes):
                            p_nick = clean(t_name)
                            opp_nick = home_nick if p_nick == away_nick else away_nick
                            fiat_opp_odds = x_data["spreads"][inv_fiat].get(opp_nick)
                            if fiat_opp_odds:
                                poly_ask = clients.get_clob_best_ask(raw_tokens[idx])
                                if poly_ask:
                                    game_output.append(f"   [Spread {poly_line}] Poly {p_nick} / Pin {opp_nick} | Pin: {float(fiat_opp_odds):<5} | Poly: {round(float(poly_ask)*100, 1)}%")
                                    arb_sum = poly_ask + (Decimal("1") / fiat_opp_odds)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, fiat_opp_odds, poly_ask, arb_sum, f"Spread {poly_line}", p_nick, f"{opp_nick} ({inv_fiat})"))

                # Attribute 5: Team Totals
                elif m_type == 'team_totals':
                    market_title = str(m.get('question', '')).lower()
                    target_team = home_nick if home_nick in market_title else (away_nick if away_nick in market_title else None)
                    if target_team and poly_line in x_data["team_totals"].get(target_team, {}):
                        norm = [str(o).lower().strip() for o in raw_outcomes]
                        if "over" in norm and "under" in norm:
                            o_idx, u_idx = norm.index("over"), norm.index("under")
                            xb_under, xb_over = x_data["team_totals"][target_team][poly_line].get('under'), x_data["team_totals"][target_team][poly_line].get('over')

                            if xb_under:
                                p_over_ask = clients.get_clob_best_ask(raw_tokens[o_idx])
                                if p_over_ask:
                                    game_output.append(f"   [{target_team.title()} Total {poly_line}] Poly O / Pin U | Pin: {float(xb_under):<5} | Poly: {round(float(p_over_ask)*100, 1)}%")
                                    arb_sum = p_over_ask + (Decimal("1") / xb_under)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_under, p_over_ask, arb_sum, f"{target_team.title()} Total {poly_line}", "OVER", "UNDER"))
                            
                            if xb_over:
                                p_under_ask = clients.get_clob_best_ask(raw_tokens[u_idx])
                                if p_under_ask:
                                    game_output.append(f"   [{target_team.title()} Total {poly_line}] Poly U / Pin O | Pin: {float(xb_over):<5} | Poly: {round(float(p_under_ask)*100, 1)}%")
                                    arb_sum = p_under_ask + (Decimal("1") / xb_over)
                                    if arb_sum < 1: opportunities.append(_build_opp(x_data, xb_over, p_under_ask, arb_sum, f"{target_team.title()} Total {poly_line}", "UNDER", "OVER"))

            # --- PRINT THE ROWS OR A FALLBACK MESSAGE ---
            if game_output:
                for row in game_output:
                    logger.info(row)
            else:
                logger.info("   [!] Safely skipped all markets (No matching lines or empty order books).")
