package demo;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {
    public Order save(Order order) {
        return order;
    }

    public java.util.Optional<Order> findById(Long id) {
        return java.util.Optional.empty();
    }
}
