from flask import Flask, jsonify, request
import json
import sqlite3
from datetime import datetime
import os
import re

app = Flask(__name__)

# Fiyat temizleme fonksiyonu
def clean_price(price_str):
    if not price_str or price_str == "":
        return 0.0

    # Türkçe fiyat formatını temizle (1.234,56 -> 1234.56)
    price_str = str(price_str).strip()

    # Binlik ayraçları (nokta) ve ondalık ayracını (virgül) düzelt
    if '.' in price_str and ',' in price_str:
        # Örnek: "1.234,56" -> "1234.56"
        price_str = price_str.replace('.', '').replace(',', '.')
    elif '.' in price_str:
        # Örnek: "31.432.11" -> "31432.11"
        parts = price_str.split('.')
        if len(parts) > 2:
            # Son parça ondalık kısım mı kontrol et
            if len(parts[-1]) == 2:  # Son 2 haneli ise ondalık olabilir
                price_str = ''.join(parts[:-1]) + '.' + parts[-1]
            else:
                price_str = price_str.replace('.', '')
        else:
            price_str = price_str.replace('.', '')
    elif ',' in price_str:
        # Örnek: "1234,56" -> "1234.56"
        price_str = price_str.replace(',', '.')

    # Sadece sayısal karakterleri ve ondalık noktasını al
    price_str = re.sub(r'[^\d.]', '', price_str)

    try:
        return float(price_str)
    except ValueError:
        print(f"⚠️  Fiyat dönüştürülemedi: {price_str} -> 0.0 olarak ayarlandı")
        return 0.0

# SQLite veritabanı oluştur (RAM dostu)
def init_db():
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    # İlaçlar tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS ilaclar
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ilac_adi TEXT,
                  barkod TEXT,
                  atc_kodu TEXT,
                  firma_adi TEXT,
                  etiket_fiyati REAL,
                  aciklama TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Etkin maddeler tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS etkin_maddeler
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ilac_id INTEGER,
                  etkin_madde TEXT,
                  miktar TEXT,
                  birim TEXT,
                  FOREIGN KEY(ilac_id) REFERENCES ilaclar(id))''')

    conn.commit()
    conn.close()

# JSON verisini SQLite'a yükle
def load_data_to_db():
    if not os.path.exists('19k_ilacdata.json'):
        return {"error": "JSON dosyası bulunamadı"}

    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    # Veri zaten yüklü mü kontrol et
    c.execute("SELECT COUNT(*) FROM ilaclar")
    if c.fetchone()[0] > 0:
        conn.close()
        return {"message": "Veri zaten yüklü"}

    with open('19k_ilacdata.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    success_count = 0
    error_count = 0

    for ilac in data:
        try:
            # Fiyatı temizle
            fiyat_str = ilac['Fiyat bilgileri']['Etiket fiyatı']
            temiz_fiyat = clean_price(fiyat_str)

            # İlaç bilgilerini ekle
            c.execute('''INSERT INTO ilaclar
                        (ilac_adi, barkod, atc_kodu, firma_adi, etiket_fiyati, aciklama)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (ilac['İlaç adı'],
                      ilac['Kod bilgileri']['Barkod'],
                      ilac['Kod bilgileri']['ATC kodu'],
                      ilac['Firma bilgileri']['Firma adı'],
                      temiz_fiyat,
                      ilac.get('aciklama', '')))

            ilac_id = c.lastrowid

            # Etkin maddeleri ekle
            for madde in ilac['Etkin maddeler']:
                c.execute('''INSERT INTO etkin_maddeler
                            (ilac_id, etkin_madde, miktar, birim)
                            VALUES (?, ?, ?, ?)''',
                         (ilac_id,
                          madde['Etkin madde'],
                          madde['Miktar'],
                          madde['Birim']))

            success_count += 1

        except Exception as e:
            error_count += 1
            print(f"❌ Hata: {ilac['İlaç adı']} - {str(e)}")
            continue

    conn.commit()
    conn.close()

    return {
        "message": f"✅ {success_count} ilaç başarıyla yüklendi, ❌ {error_count} hata"
    }

# API Routes
@app.route('/')
def home():
    return jsonify({
        "message": "Nabisystem İlaç API",
        "yapimci": "sukazatkinis",
        "telegram": "ulaşa bilirsiniz",
        "version": "1.0",
        "endpoints": {
            "/ilaclar": "Tüm ilaçları listele",
            "/ilac/<barkod>": "Barkod ile ilaç ara",
            "/ara/<ilac_adi>": "İlaç adı ile ara",
            "/firma/<firma_adi>": "Firmaya göre ara",
            "/etkin-madde/<madde>": "Etkin maddeye göre ara",
            "/stats": "İstatistikler"
        }
    })

# İstatistikler
@app.route('/stats')
def get_stats():
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM ilaclar")
    total_ilaclar = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT firma_adi) FROM ilaclar")
    total_firmalar = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM etkin_maddeler")
    total_etkin_maddeler = c.fetchone()[0]

    c.execute("SELECT AVG(etiket_fiyati) FROM ilaclar WHERE etiket_fiyati > 0")
    ortalama_fiyat = c.fetchone()[0]

    conn.close()

    return jsonify({
        "toplam_ilac": total_ilaclar,
        "toplam_firma": total_firmalar,
        "toplam_etkin_madde": total_etkin_maddeler,
        "ortalama_fiyat": round(ortalama_fiyat, 2) if ortalama_fiyat else 0
    })

# Tüm ilaçları getir (sayfalı)
@app.route('/ilaclar')
def get_ilaclar():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    offset = (page - 1) * limit

    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute('''
        SELECT i.id, i.ilac_adi, i.barkod, i.atc_kodu, i.firma_adi, i.etiket_fiyati, i.aciklama,
               GROUP_CONCAT(em.etkin_madde || ' (' || em.miktar || ' ' || em.birim || ')') as maddeler
        FROM ilaclar i
        LEFT JOIN etkin_maddeler em ON i.id = em.ilac_id
        GROUP BY i.id
        LIMIT ? OFFSET ?
    ''', (limit, offset))

    ilaclar = []
    for row in c.fetchall():
        ilaclar.append({
            "id": row[0],
            "ilac_adi": row[1],
            "barkod": row[2],
            "atc_kodu": row[3],
            "firma_adi": row[4],
            "etiket_fiyati": row[5],
            "aciklama": row[6],
            "etkin_maddeler": row[7].split(',') if row[7] else []
        })

    conn.close()

    return jsonify({
        "page": page,
        "limit": limit,
        "total_items": len(ilaclar),
        "ilaclar": ilaclar
    })

# Barkod ile ara
@app.route('/ilac/<barkod>')
def get_ilac_by_barkod(barkod):
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute('''
        SELECT i.*,
               GROUP_CONCAT(em.etkin_madde || '|' || em.miktar || '|' || em.birim) as maddeler
        FROM ilaclar i
        LEFT JOIN etkin_maddeler em ON i.id = em.ilac_id
        WHERE i.barkod = ?
        GROUP BY i.id
    ''', (barkod,))

    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "İlaç bulunamadı"}), 404

    # Etkin maddeleri parse et
    etkin_maddeler = []
    if row[8]:  # maddeler sütunu
        for madde in row[8].split(','):
            parts = madde.split('|')
            if len(parts) == 3:
                etkin_maddeler.append({
                    "Etkin madde": parts[0],
                    "Miktar": parts[1],
                    "Birim": parts[2]
                })

    return jsonify({
        "ilac_adi": row[1],
        "barkod": row[2],
        "atc_kodu": row[3],
        "firma_adi": row[4],
        "etiket_fiyati": row[5],
        "aciklama": row[6],
        "etkin_maddeler": etkin_maddeler,
        "created_at": row[7]
    })

# İlaç adı ile ara
@app.route('/ara/<ilac_adi>')
def search_ilac(ilac_adi):
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute('''
        SELECT i.id, i.ilac_adi, i.barkod, i.firma_adi, i.etiket_fiyati
        FROM ilaclar i
        WHERE i.ilac_adi LIKE ?
        LIMIT 20
    ''', (f'%{ilac_adi}%',))

    ilaclar = []
    for row in c.fetchall():
        ilaclar.append({
            "id": row[0],
            "ilac_adi": row[1],
            "barkod": row[2],
            "firma_adi": row[3],
            "etiket_fiyati": row[4]
        })

    conn.close()

    return jsonify({
        "search_term": ilac_adi,
        "results": ilaclar
    })

# Firma ile ara
@app.route('/firma/<firma_adi>')
def search_by_firma(firma_adi):
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute('''
        SELECT ilac_adi, barkod, etiket_fiyati
        FROM ilaclar
        WHERE firma_adi LIKE ?
        LIMIT 50
    ''', (f'%{firma_adi}%',))

    ilaclar = [{"ilac_adi": row[0], "barkod": row[1], "etiket_fiyati": row[2]}
               for row in c.fetchall()]

    conn.close()

    return jsonify({
        "firma": firma_adi,
        "results": ilaclar
    })

# Etkin madde ile ara
@app.route('/etkin-madde/<madde>')
def search_by_etkin_madde(madde):
    conn = sqlite3.connect('ilacdata.db')
    c = conn.cursor()

    c.execute('''
        SELECT i.ilac_adi, i.barkod, i.firma_adi, i.etiket_fiyati,
               em.etkin_madde, em.miktar, em.birim
        FROM ilaclar i
        JOIN etkin_maddeler em ON i.id = em.ilac_id
        WHERE em.etkin_madde LIKE ?
        LIMIT 30
    ''', (f'%{madde}%',))

    ilaclar = []
    for row in c.fetchall():
        ilaclar.append({
            "ilac_adi": row[0],
            "barkod": row[1],
            "firma_adi": row[2],
            "etiket_fiyati": row[3],
            "etkin_madde": f"{row[4]} ({row[5]} {row[6]})"
        })

    conn.close()

    return jsonify({
        "etkin_madde": madde,
        "results": ilaclar
    })

if __name__ == '__main__':
    # Veritabanını başlat
    init_db()
    print("📊 Veritabanı hazır...")

    # JSON verisini yükle
    result = load_data_to_db()
    print(f"📁 {result}")

    # API'yi başlat
    print("🚀 API başlatılıyor... http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
~/downloads $
