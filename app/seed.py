import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models import User, Transaction, Segment, SegmentType, SegmentDependency

def run_seed():
    print("⏳ Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    if db.query(Segment).first():
        print("✅ Database is already seeded! Skipping.")
        db.close()
        return
    
    print("🌱 Seeding Users...")
    u1 = User(name="Alice (Active VIP)")
    u2 = User(name="Bob (Active Low Spender)")
    u3 = User(name="Charlie (Inactive)")
    db.add_all([u1, u2, u3])
    db.commit()

    print("💸 Seeding Transactions...")
    db.add(Transaction(user_id=u1.id, amount=550000))
    db.add(Transaction(user_id=u2.id, amount=2000))
    db.commit()

    print("📊 Seeding Segments...")
    seg_active = Segment(
        name="Active Buyers",
        type=SegmentType.DYNAMIC,
        rules_json={"field": "transaction_count", "op": ">=", "value": 1}
    )
    
    seg_high = Segment(
        name="VIP High Spenders",
        type=SegmentType.DYNAMIC,
        rules_json={"field": "total_spend", "op": ">", "value": 5000}
    )

    seg_dependent = Segment(
        name="Target Audience (Dependent)",
        type=SegmentType.DYNAMIC,
        rules_json={"field": "segment_id", "op": "in", "value": [1]} 
    )

    seg_static = Segment(
        name="March Campaign Audience",
        type=SegmentType.STATIC,
        rules_json=None
    )

    db.add_all([seg_active, seg_high, seg_dependent, seg_static])
    db.commit()

    print("🔗 Seeding Dependencies...")
    dep = SegmentDependency(parent_segment_id=seg_active.id, child_segment_id=seg_dependent.id)
    db.add(dep)
    db.commit()

    print("🎉 Seeding complete! Database is ready.")
    db.close()

if __name__ == "__main__":
    run_seed()