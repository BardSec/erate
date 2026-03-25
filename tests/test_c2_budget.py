from app.models.erate import C2Budget, FundingYear


def test_c2_budget_calculation():
    """Test C2 budget calculation logic."""
    # Standard: enrollment * multiplier vs schools * floor
    # 2500 * 167 = 417,500 vs 3 * 25,000 = 75,000
    result = C2Budget.calculate_budget(2500, 3, 167.0, 25000.0)
    assert result == 417500.0

    # Floor wins for small districts
    # 50 * 167 = 8,350 vs 2 * 25,000 = 50,000
    result = C2Budget.calculate_budget(50, 2, 167.0, 25000.0)
    assert result == 50000.0


def test_c2_budget_new_cycle():
    """Test FY2026-2030 multiplier."""
    result = C2Budget.calculate_budget(2500, 3, 201.57, 30175.0)
    assert result == 503925.0  # 2500 * 201.57


def test_c2_budget_remaining(db):
    """Test amount remaining calculation."""
    budget = C2Budget(
        tenant_id=1,
        cycle_start_year=2021,
        cycle_end_year=2025,
        multiplier_per_student=167.0,
        funding_floor=25000.0,
        total_enrollment=2500,
        calculated_budget=417500.0,
        spent_to_date=200000.0,
    )
    assert budget.amount_remaining == 217500.0
    assert budget.percent_used == 47.9


def test_discount_rate_calculation():
    """Test E-rate discount rate calculation."""
    # Urban, 65% NSLP -> 80%
    assert FundingYear.calculate_discount_rate(65, 'urban') == 80
    # Rural, 65% NSLP -> 80%
    assert FundingYear.calculate_discount_rate(65, 'rural') == 80
    # Urban, 40% NSLP -> 60%
    assert FundingYear.calculate_discount_rate(40, 'urban') == 60
    # Rural, 40% NSLP -> 70%
    assert FundingYear.calculate_discount_rate(40, 'rural') == 70
    # Urban, 85% NSLP -> 90%
    assert FundingYear.calculate_discount_rate(85, 'urban') == 90
    # Urban, 15% NSLP -> 40%
    assert FundingYear.calculate_discount_rate(15, 'urban') == 40
