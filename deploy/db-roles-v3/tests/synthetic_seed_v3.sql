-- R-5 synthetic data (disposable test cluster only). Every row is invented: symbols start with SYN, nothing is
-- copied from production. Rows straddle the FORWARD_HOLDOUT boundary (2026-08-19 09:33:46 UTC) on purpose, so the
-- research boundary can be tested; the conservative rule treats the boundary instant itself as holdout.
INSERT INTO risk_management (date, is_trading_paused, pause_reason) VALUES ('2026-09-11', true, 'risk:loss_streak_halt');

INSERT INTO signals (symbol, timeframe, market_condition, signal_time, entry_price, target_1, target_2, target_3,
                     stop_loss, score, telegram_sent, is_paper_trade, strategy_version) VALUES
  ('SYNPREAUSDT', '15m', 'neutral', '2026-08-10 12:00:00', 1, 1.01, 1.02, 1.03, 0.99, 4, true, true, 'syn'),
  ('SYNPREBUSDT', '1d',  'neutral', '2026-08-19 09:33:45', 1, 1.01, 1.02, 1.03, 0.99, 4, true, true, 'syn'),
  ('SYNPOSTAUSDT','15m', 'neutral', '2026-08-19 09:33:46', 1, 1.01, 1.02, 1.03, 0.99, 4, true, true, 'syn'),
  ('SYNPOSTBUSDT','15m', 'neutral', '2026-10-10 12:00:00', 1, 1.01, 1.02, 1.03, 0.99, 4, true, true, 'syn');

INSERT INTO active_trades (signal_id, symbol, entry_price, target_1, target_2, target_3, stop_loss, timeframe,
                           is_paper_trade, opened_at, status)
  SELECT id, symbol, 1, 1.01, 1.02, 1.03, 0.99, timeframe, true, signal_time + interval '1 minute', 'closed'
  FROM signals WHERE symbol LIKE 'SYNP%';
INSERT INTO trade_results (signal_id, symbol, entry_price, exit_price, exit_time, result, profit_percent, profit_usdt)
  SELECT id, symbol, 1, 0.98, signal_time + interval '1 hour', 'LOSS', -2, -1 FROM signals WHERE symbol LIKE 'SYNP%';
INSERT INTO trade_target_fills (active_trade_id, signal_id, symbol, target_number, fill_price, quantity_fraction,
                                notional_usdt, gross_profit_percent_contribution, gross_profit_usdt, filled_at)
  SELECT a.id, a.signal_id, a.symbol, 1, 1.01, 0.25, 12.5, 0.25, 0.125, a.opened_at + interval '5 minutes'
  FROM active_trades a WHERE a.symbol LIKE 'SYNP%';

-- A synthetic 7-loss streak (no signal link) for the telegram recovery path, as in the P0 suite.
INSERT INTO trade_results (signal_id, symbol, entry_price, exit_price, exit_time, result, profit_percent, profit_usdt)
  SELECT NULL, 'SYNSTREAKUSDT', 1, 0.98, now() - (g || ' minutes')::interval, 'LOSS', -2, -1 FROM generate_series(1, 7) g;
