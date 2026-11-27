"""Брендовые и навигационные запросы, которые выбрасываются из ниш (общие для niche-build и niche-score)."""
import re
# Навигационные запросы брендов (МФО, банки, лотереи): выдача по бренду закрывается его владельцем, как у `mostbet`.
# Такие ключи выброшены из ниши целиком — и из выборки, и из частотности ниши.
BRAND = re.compile(r'(кредит ?плюс|кредит ?365|365 ?(кредит|займ)|займ ?365|кредит ?бар|^а кредит|уан ?кредит|оне ?кредит|'
                   r'селфи ?кредит|бз ?займ|би ?кредит|квику|сат ?кредит|solva|сольва|kaspi|каспи|halyk|халык|хоум ?кредит|home ?credit|'
                   r'кредит ?азия|ishonch|uzum|tbc|tbs kredit|mahalla bank|abb|kapital ?bank|nova ?kredit|azpay|yap[ıi] ?kredi|hangikredi|'
                   r'bizon|azerlotereya|birbank|milli ?piyango|millipiyango|'
                   r'credit ?365|iute|easy ?credit|credit ?prime|microinvest|mikro ?kapital|loteria (na[tţț]ional|moldovei))')
# Доски объявлений и порталы вакансий в Молдове (999.md, «работа мд») — навигационные запросы к одному сайту, в любой нише.
NAV = re.compile(r'(\b999\b|999\.md|работа ?мд|rabota ?md|\bolx\b|олх)')
def brand(r): return (r['niche'] in ('loans', 'lottery') and bool(BRAND.search(r['keyword'].lower()))) or bool(NAV.search(r['keyword'].lower()))
