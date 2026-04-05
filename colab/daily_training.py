"""
نوتبوك التدريب اليومي على Google Colab
يُشغَّل يومياً لتحديث أوزان المؤشرات
"""

# ==================== الخلية 1: التثبيت ====================
# !pip install asyncpg pandas scikit-learn anthropic google-auth google-auth-oauthlib google-auth-httplib2

# ==================== الخلية 2: الاستيراد ====================
import os
import json
import asyncio
import asyncpg
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import anthropic
import warnings
warnings.filterwarnings('ignore')

print("✅ تم تحميل المكتبات")

# ==================== الخلية 3: الاتصال ====================
# إعدادات الاتصال (تُضاف كـ Colab Secrets)
DB_CONFIG = {
    'host': os.environ.get('POSTGRES_HOST'),
    'port': int(os.environ.get('POSTGRES_PORT', 5432)),
    'database': os.environ.get('POSTGRES_DB'),
    'user': os.environ.get('POSTGRES_USER'),
    'password': os.environ.get('POSTGRES_PASSWORD'),
}
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

async def get_connection():
    return await asyncpg.connect(**DB_CONFIG)

print("✅ إعدادات الاتصال جاهزة")

# ==================== الخلية 4: جلب البيانات ====================
async def fetch_training_data():
    """جلب بيانات الصفقات للتدريب"""
    conn = await get_connection()
    
    # جلب الإشارات ونتائجها
    rows = await conn.fetch("""
        SELECT 
            s.symbol,
            s.market_condition,
            s.score,
            s.score_details,
            tr.result,
            tr.profit_percent,
            tr.target_reached
        FROM signals s
        JOIN trade_results tr ON s.id = tr.signal_id
        WHERE s.signal_time > NOW() - INTERVAL '90 days'
        AND tr.result IS NOT NULL
        ORDER BY s.signal_time DESC
    """)
    
    await conn.close()
    
    if not rows:
        print("⚠️ لا توجد بيانات كافية للتدريب")
        return None
    
    # تحويل إلى DataFrame
    data = []
    for row in rows:
        details = json.loads(row['score_details']) if isinstance(row['score_details'], str) else row['score_details']
        entry = {
            'symbol': row['symbol'],
            'market_condition': row['market_condition'],
            'total_score': row['score'],
            'result': 1 if row['result'] == 'WIN' else 0,
            'profit': float(row['profit_percent'] or 0),
        }
        # إضافة تفاصيل المؤشرات
        for indicator, value in (details or {}).items():
            entry[f'ind_{indicator}'] = float(value)
        
        data.append(entry)
    
    df = pd.DataFrame(data)
    print(f"✅ تم جلب {len(df)} صفقة للتدريب")
    print(f"📊 نسبة الربح: {df['result'].mean()*100:.1f}%")
    
    return df

df = asyncio.run(fetch_training_data())

# ==================== الخلية 5: تدريب النموذج ====================
async def train_and_update_weights(df):
    """تدريب النموذج وتحديث الأوزان"""
    if df is None or len(df) < 20:
        print("⚠️ بيانات غير كافية - نحتاج 20 صفقة على الأقل")
        return
    
    # تحديث الأوزان لكل حالة سوق
    market_conditions = df['market_condition'].unique()
    weight_updates = {}
    
    for condition in market_conditions:
        condition_df = df[df['market_condition'] == condition]
        if len(condition_df) < 5:
            continue
        
        # حساب معدل النجاح لكل مؤشر في هذه الحالة
        indicator_cols = [c for c in condition_df.columns if c.startswith('ind_')]
        
        for col in indicator_cols:
            indicator = col.replace('ind_', '')
            
            # حساب الارتباط بين المؤشر والنجاح
            indicator_data = condition_df[col].fillna(0)
            success_data = condition_df['result']
            
            if indicator_data.std() == 0:
                continue
            
            correlation = indicator_data.corr(success_data)
            
            # الوزن الجديد بناءً على الارتباط
            if not np.isnan(correlation):
                new_weight = max(0.3, min(2.0, 1.0 + correlation))
                
                key = f"{indicator}_{condition}"
                weight_updates[key] = {
                    'indicator': indicator,
                    'condition': condition,
                    'weight': round(new_weight, 4),
                    'success_rate': round(float(success_data.mean()), 4),
                    'sample_size': len(condition_df)
                }
        
        print(f"✅ {condition}: تم تحليل {len(condition_df)} صفقة")
    
    # تحديث قاعدة البيانات
    if weight_updates:
        conn = await get_connection()
        
        for key, data in weight_updates.items():
            await conn.execute("""
                UPDATE indicator_weights
                SET weight = $1,
                    success_rate = $2,
                    last_updated = NOW()
                WHERE indicator_name = $3
                AND market_condition = $4
            """, data['weight'], data['success_rate'],
                data['indicator'], data['condition'])
        
        # حفظ سجل التدريب
        total_trades = len(df)
        win_rate = float(df['result'].mean())
        avg_profit = float(df['profit'].mean())
        
        await conn.execute("""
            INSERT INTO learning_log (
                model_version, total_trades_analyzed,
                win_rate, avg_profit, changes_made
            ) VALUES ($1, $2, $3, $4, $5)
        """,
            f"v_{datetime.now().strftime('%Y%m%d')}",
            total_trades,
            win_rate,
            avg_profit,
            json.dumps({'weights_updated': len(weight_updates)})
        )
        
        await conn.close()
        print(f"✅ تم تحديث {len(weight_updates)} وزن في قاعدة البيانات")
        print(f"📊 معدل الربح الإجمالي: {win_rate*100:.1f}%")
        print(f"💰 متوسط الربح: {avg_profit:.2f}%")
    
    return weight_updates

if df is not None:
    updates = asyncio.run(train_and_update_weights(df))

# ==================== الخلية 6: تحليل Claude ====================
async def claude_analysis(df, updates):
    """تحليل النتائج بواسطة Claude"""
    if df is None:
        return
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # إحصائيات للتحليل
    stats = {
        'total_trades': len(df),
        'win_rate': f"{df['result'].mean()*100:.1f}%",
        'avg_profit': f"{df['profit'].mean():.2f}%",
        'best_market': df.groupby('market_condition')['result'].mean().idxmax(),
        'worst_market': df.groupby('market_condition')['result'].mean().idxmin(),
        'weights_updated': len(updates) if updates else 0
    }
    
    prompt = f"""أنت محلل تداول خبير. حلل نتائج بوت التداول:

الإحصائيات:
{json.dumps(stats, ensure_ascii=False, indent=2)}

أعطني:
1. تقييم مختصر للأداء
2. أهم مشكلة تراها
3. توصية واحدة للتحسين

الرد بالعربية، 3 نقاط فقط."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    
    analysis = response.content[0].text
    print("\n🤖 تحليل Claude:")
    print(analysis)
    
    # حفظ التحليل
    conn = await get_connection()
    await conn.execute("""
        UPDATE learning_log
        SET claude_analysis = $1
        WHERE id = (SELECT MAX(id) FROM learning_log)
    """, analysis)
    await conn.close()

if df is not None and updates:
    asyncio.run(claude_analysis(df, updates))

print("\n✅ اكتمل التدريب اليومي!")
print(f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
